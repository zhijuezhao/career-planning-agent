from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.agent.langgraph_agent import build_agent_graph, compile_agent
from app.core.agent.nodes import AgentState, call_model, execute_tools, should_continue
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph.state import CompiledStateGraph

# ── nodes.py tests ─────────────────────────────────────────────────────────


class MockLLM:
    """Minimal mock that mimics BaseChatModel.ainvoke."""

    def __init__(self, tool_calls: list | None = None):
        self._tool_calls = tool_calls or []

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content="模型回复", tool_calls=self._tool_calls)


class TestNodes:
    @pytest.mark.asyncio
    async def test_call_model_no_tool_calls(self):
        state: AgentState = {"messages": [HumanMessage(content="你好")]}
        llm = MockLLM(tool_calls=[])

        result = await call_model(state, config={"configurable": {"llm": llm}})

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "模型回复"
        assert result["next"] == "end"

    @pytest.mark.asyncio
    async def test_call_model_with_tool_calls(self):
        state: AgentState = {"messages": [HumanMessage(content="查天气")]}
        fake_tool_call = {"name": "weather", "args": {"city": "北京"}, "id": "call_1"}
        llm = MockLLM(tool_calls=[fake_tool_call])

        result = await call_model(state, config={"configurable": {"llm": llm}})

        assert result["next"] == "tools"

    @pytest.mark.asyncio
    async def test_execute_tools(self):
        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "weather"
        mock_tool.ainvoke.return_value = "北京今天25°C"

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="我来查天气",
                    tool_calls=[{"name": "weather", "args": {"city": "北京"}, "id": "call_1"}],
                )
            ]
        }

        result = await execute_tools(
            state, config={"configurable": {"tools_by_name": {"weather": mock_tool}}}
        )

        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert result["messages"][0].content == "北京今天25°C"
        assert result["messages"][0].tool_call_id == "call_1"
        assert result["next"] == "continue"

    @pytest.mark.asyncio
    async def test_execute_tools_tool_not_found(self):
        state: AgentState = {
            "messages": [
                AIMessage(
                    content="调用未知工具",
                    tool_calls=[{"name": "unknown_tool", "args": {}, "id": "call_2"}],
                )
            ]
        }

        result = await execute_tools(state, config={"configurable": {"tools_by_name": {}}})

        assert "not found" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_execute_tools_injects_runtime_identity(self):
        """运行时身份注入：`user_id` / `profile_id` 模型不可能知道，必须由 configurable 补齐。

        `profile_id` 与 `user_id` 是 **1:1 约定**（`snapshot_service` 里就写 `profile_id=user_id`）
        → 不注入的话 `generate_career_report(user_id, profile_id, ...)` 一调就报错。
        用真实 `@tool` 而不是 Mock：顺带验证 pydantic v2 的 `args_schema.model_fields` 读取路径。
        """

        @tool
        async def _fake_report(
            user_id: int, profile_id: int, target_job: str | None = None
        ) -> str:
            """Fake report tool for injection test."""
            return f"{user_id}|{profile_id}|{target_job}"

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="生成报告",
                    tool_calls=[
                        {
                            "name": "_fake_report",
                            "args": {"target_job": "前端开发"},
                            "id": "call_3",
                        }
                    ],
                )
            ]
        }

        result = await execute_tools(
            state,
            config={
                "configurable": {
                    "tools_by_name": {"_fake_report": _fake_report},
                    "user_id": 42,
                }
            },
        )

        # user_id 与 profile_id 都被注入；模型自己给的 target_job 不被覆盖
        assert result["messages"][0].content == "42|42|前端开发"

    @pytest.mark.asyncio
    async def test_call_model_without_llm_raises_clear_error(self):
        """config 没带 llm 时给**明确**错误（此前是 AttributeError: 'NoneType' ...）。"""
        with pytest.raises(ValueError) as exc:
            await call_model(
                {"messages": [HumanMessage(content="你好")]}, config={"configurable": {}}
            )
        assert "configurable" in str(exc.value)

    def test_should_continue_returns_continue(self):
        assert should_continue({"next": "continue"}) == "continue"

    def test_should_continue_returns_end(self):
        assert should_continue({"next": "end"}) == "end"

    def test_should_continue_defaults_to_end(self):
        assert should_continue({}) == "end"


# ── langgraph_agent.py tests ────────────────────────────────────────────────


class TestLangGraphAgent:
    def test_build_agent_graph_structure(self):
        mock_llm = MagicMock()
        graph = build_agent_graph(mock_llm)

        node_names = set(graph.nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names

    def test_compile_agent_returns_compiled_graph(self):
        mock_llm = MagicMock()
        compiled = compile_agent(mock_llm)

        assert isinstance(compiled, CompiledStateGraph)

    @pytest.mark.asyncio
    async def test_agent_graph_simple_invoke(self):
        """Integration test: mock LLM without tool calls → should end immediately."""

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="最终回答", tool_calls=[])
        compiled = compile_agent(mock_llm)

        result = await compiled.ainvoke(
            {"messages": [HumanMessage(content="你好")]},
            {"configurable": {"llm": mock_llm, "tools_by_name": {}}},
        )

        assert len(result["messages"]) >= 2  # HumanMessage + AIMessage
        assert result["messages"][-1].content == "最终回答"
