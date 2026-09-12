from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import add_messages
from loguru import logger


class AgentState(TypedDict, total=False):
    """State for a ReAct agent loop.

    Fields:
        messages: Conversation history (system, human, AI, tool messages).
                  Uses ``add_messages`` reducer to merge by ID.
        next: Conditional edge signal — "tools" to execute tools, "end" to finish.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next: str


async def call_model(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Invoke the LLM with the current message list.

    Expects ``config["configurable"]["llm"]`` to be a ``BaseChatModel``
    with tools already bound (via ``.bind_tools()``).
    """
    llm = config["configurable"]["llm"] if config else None
    messages = state["messages"]

    response = await llm.ainvoke(messages)
    logger.info("Agent call_model | msg_count={} | tool_calls={}", len(messages), len(response.tool_calls))

    return {"messages": [response], "next": "tools" if response.tool_calls else "end"}


async def execute_tools(state: AgentState, config: RunnableConfig | None = None) -> dict[str, list[ToolMessage]]:
    """Execute tool calls from the last AI message.

    Expects ``config["configurable"]["tools_by_name"]`` to be a dict mapping
    tool names to ``BaseTool`` instances.
    """
    tools_by_name: dict[str, BaseTool] = (config or {}).get("configurable", {}).get("tools_by_name", {})
    db = (config or {}).get("configurable", {}).get("db")
    user_id = (config or {}).get("configurable", {}).get("user_id")
    last_message = state["messages"][-1]

    tool_messages: list[ToolMessage] = []
    for tool_call in last_message.tool_calls:
        tool = tools_by_name.get(tool_call["name"])
        if tool is None:
            logger.warning("Tool not found | name={}", tool_call["name"])
            content = f"Error: tool '{tool_call['name']}' not found."
        else:
            try:
                # Inject db and user_id into tool args
                args = dict(tool_call["args"])
                tool_fields = (
                    tool.args_schema.__fields__
                    if hasattr(tool, "args_schema") and tool.args_schema
                    else {}
                )
                if db is not None and "db" in tool_fields:
                    args["db"] = db
                if user_id is not None:
                    # Auto-fill user_id if not provided
                    if "user_id" in tool_fields and "user_id" not in args:
                        args["user_id"] = user_id
                result = await tool.ainvoke(args)
                content = str(result)
                logger.info("Tool executed | name={} | args={}", tool_call["name"], tool_call["args"])
            except Exception as exc:
                content = f"Error executing '{tool_call['name']}': {exc}"
                logger.warning("Tool execution failed | name={} | error={}", tool_call["name"], exc)

        tool_messages.append(
            ToolMessage(content=content, tool_call_id=tool_call["id"])
        )

    return {"messages": tool_messages, "next": "continue"}


def should_continue(state: AgentState) -> str:
    """Determine the next step after tool execution.

    Returns:
        "continue" → call_model again (more LLM reasoning).
        "end" → finish the agent loop.
    """
    return state.get("next", "end")
