from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import add_messages
from loguru import logger

# 说明（2026-09-25）：
# 依赖通过 **RunnableConfig.configurable** 逐次调用传入，不使用模块级全局。
# 曾经出现过一版用 `set_agent_context()` 全局变量传 llm/tools 的实现 —— 那是**并发不安全**的：
# 两个学生同时对话会互相覆盖上下文（A 的 db/user_id 被 B 顶掉），且全仓库无人调用它，
# 结果 agent 链整条失效（5 个单测红）。LangGraph 的惯用法就是 configurable，
# 它随每次 invoke 独立，天然满足隔离。
#
# chat 调用点传的 config：
#   {"configurable": {"llm": <已 bind_tools 的模型>, "tools_by_name": {...},
#                     "db": <AsyncSession>, "user_id": <int>,
#                     "viz_sink": <list>},   # 工具产出的图收集到这里（见 _split_tool_viz）
#    "recursion_limit": <步数上限>}


class AgentState(TypedDict, total=False):
    """State for a ReAct agent loop.

    Fields:
        messages: Conversation history (system, human, AI, tool messages).
                  Uses ``add_messages`` reducer to merge by ID.
        next: Conditional edge signal — "tools" to execute tools, "end" to finish.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next: str


def _tool_field_names(tool: BaseTool) -> set[str]:
    """取工具的入参字段名（兼容 pydantic v2 与 v1）。

    v2 是 `model_fields`，v1 才是 `__fields__`；langchain 的 `args_schema` 在 v2 下
    仍是 pydantic v2 模型，旧写法 `args_schema.__fields__` 只是**弃用别名**，会随版本失效。
    """
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return set()
    fields = getattr(schema, "model_fields", None)
    if fields is None:
        fields = getattr(schema, "__fields__", None)
    return set(fields or {})


def _inject_runtime_args(
    tool: BaseTool,
    raw_args: dict[str, Any],
    *,
    db: Any = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """把「模型不可能知道」的运行时依赖注入工具入参。

    - `db`：需要外部 session 的工具；
    - `user_id`：当前登录用户；
    - `profile_id`：能力画像 id，与 `user_id` 是 **1:1 约定**
      （`snapshot_service` 里就写着 `profile_id=user_id`，`report_service` 亦同）。

    🔒 **这三个是"运行时身份"，一律以服务端值为准、强制覆盖模型给的值**（2026-09-27 P4 收紧）。
    早先的写法是"模型没给才注入"（`"user_id" not in args`），那等于把身份参数交给模型：
    P4 新增的 `user_snapshot` 会读**个人画像** —— 只要模型（或被提示注入诱导）填一个
    `user_id=1`，学生就能读到**别人的**画像。这类参数从来不是模型该决定的。
    强制覆盖对既有工具也是纯收益：`generate_career_report(user_id, profile_id, …)`
    本来就只应作用于当前登录用户。
    """
    args = dict(raw_args)
    fields = _tool_field_names(tool)
    if db is not None and "db" in fields:
        args["db"] = db
    if user_id is not None:
        if "user_id" in fields:
            args["user_id"] = user_id
        if "profile_id" in fields:
            args["profile_id"] = user_id
    return args


async def call_model(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Invoke the LLM with the current message list.

    Expects ``config["configurable"]["llm"]`` to be a ``BaseChatModel``
    with tools already bound (via ``.bind_tools()``).
    """
    llm: BaseChatModel | None = (config or {}).get("configurable", {}).get("llm")
    if llm is None:
        raise ValueError(
            "Agent 缺少 llm：请通过 config['configurable']['llm'] 传入已 bind_tools 的模型"
        )

    messages = state["messages"]
    response = await llm.ainvoke(messages)
    logger.info(
        "Agent call_model | msg_count={} | tool_calls={}", len(messages), len(response.tool_calls)
    )

    return {"messages": [response], "next": "tools" if response.tool_calls else "end"}


def _split_tool_viz(result: Any) -> tuple[Any, list[dict[str, Any]]]:
    """把工具结果里的 `viz` 载荷**摘出来**，返回 `(给模型看的结果, viz 列表)`。

    P5（2026-09-27）新增：让**工具**也能产图（此前只有 L1 工作流能产 viz）。

    ⚠️ **必须摘掉再给模型**：`viz` 里是 ECharts option（几十上百个数字与中文键），
    塞进 `ToolMessage` 就是**纯烧 token** —— 模型对"怎么画图"毫无用处，
    图由前端渲染。所以工具返回 `{"...业务数据...": ..., "viz": [...]}`，
    业务数据回给模型，`viz` 只进 `viz_sink`（供 SSE 下发 + 落库）。
    """
    if not isinstance(result, dict) or "viz" not in result:
        return result, []

    payload = {key: value for key, value in result.items() if key != "viz"}
    raw = result.get("viz")
    items = raw if isinstance(raw, list) else [raw]
    return payload, [item for item in items if isinstance(item, dict)]


async def execute_tools(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, list[ToolMessage]]:
    """Execute tool calls from the last AI message.

    Expects ``config["configurable"]["tools_by_name"]`` to be a dict mapping
    tool names to ``BaseTool`` instances（可选 ``db`` / ``user_id`` 用于参数注入，
    ``viz_sink`` 用于收集工具产出的图）。
    """
    configurable = (config or {}).get("configurable", {}) or {}
    tools_by_name: dict[str, BaseTool] = configurable.get("tools_by_name", {}) or {}
    db = configurable.get("db")
    user_id = configurable.get("user_id")
    viz_sink = configurable.get("viz_sink")

    last_message = state["messages"][-1]

    tool_messages: list[ToolMessage] = []
    for tool_call in last_message.tool_calls:
        tool = tools_by_name.get(tool_call["name"])
        if tool is None:
            logger.warning("Tool not found | name={}", tool_call["name"])
            content = f"Error: tool '{tool_call['name']}' not found."
        else:
            try:
                args = _inject_runtime_args(
                    tool, tool_call["args"], db=db, user_id=user_id
                )
                result = await tool.ainvoke(args)
                payload, viz = _split_tool_viz(result)
                if viz and isinstance(viz_sink, list):
                    viz_sink.extend(viz)
                    logger.info(
                        "Tool produced viz | name={} | items={}", tool_call["name"], len(viz)
                    )
                content = str(payload)
                logger.info("Tool executed | name={} | args={}", tool_call["name"], args)
            except Exception as exc:  # noqa: BLE001 - 工具异常要回给模型，不能中断整轮
                content = f"Error executing '{tool_call['name']}': {exc}"
                logger.warning("Tool execution failed | name={} | error={}", tool_call["name"], exc)

        tool_messages.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))

    return {"messages": tool_messages, "next": "continue"}


def should_continue(state: AgentState) -> str:
    """Determine the next step after tool execution.

    Returns:
        "continue" → call_model again (more LLM reasoning).
        "end" → finish the agent loop.
    """
    return state.get("next", "end")
