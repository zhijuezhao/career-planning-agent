from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.agent.base import BaseAgent, ReActAgent
from app.core.agent.langgraph_agent import build_agent_graph, compile_agent
from app.core.agent.nodes import AgentState, call_model, execute_tools, should_continue
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

# ── base.py tests ──────────────────────────────────────────────────────────


class TestBaseAgent:
    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseAgent(llm_gateway=MagicMock(), system_prompt="test")  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_react_agent_arun(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="你好，我是AI助手")
        mock_gateway = MagicMock()
        mock_gateway.get_model.return_value = mock_llm

        agent = ReActAgent(llm_gateway=mock_gateway, system_prompt="你是一个助手。")
        result = await agent.arun("你好")

        assert result == "你好，我是AI助手"
        mock_gateway.get_model.assert_called_once_with(None)
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_react_agent_arun_with_model_name(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="使用qwen模型回复")
        mock_gateway = MagicMock()
        mock_gateway.get_model.return_value = mock_llm

        agent = ReActAgent(llm_gateway=mock_gateway, system_prompt="", model_name="qwen")
        result = await agent.arun("测试")

        assert result == "使用qwen模型回复"
        mock_gateway.get_model.assert_called_once_with("qwen")

    @pytest.mark.asyncio
    async def test_react_agent_astream(self):
        mock_llm = MagicMock()

        async def _astream(_):
            yield AIMessage(content="token1")
            yield AIMessage(content="token2")

        mock_llm.astream = _astream
        mock_gateway = MagicMock()
        mock_gateway.get_model.return_value = mock_llm

        agent = ReActAgent(llm_gateway=mock_gateway, system_prompt="")
        tokens = [t async for t in agent.astream("你好")]

        assert tokens == ["token1", "token2"]

    @pytest.mark.asyncio
    async def test_react_agent_with_tools_bound(self):
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_llm = MagicMock()
        mock_bound = AsyncMock()
        mock_bound.ainvoke.return_value = AIMessage(content="带工具回复")
        mock_llm.bind_tools.return_value = mock_bound
        mock_gateway = MagicMock()
        mock_gateway.get_model.return_value = mock_llm

        agent = ReActAgent(llm_gateway=mock_gateway, system_prompt="", tools=[mock_tool])
        result = await agent.arun("调用工具")

        assert result == "带工具回复"
        mock_llm.bind_tools.assert_called_once_with([mock_tool])

    def test_build_messages_with_history(self):
        mock_gateway = MagicMock()
        agent = ReActAgent(llm_gateway=mock_gateway, system_prompt="系统提示。")
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]

        messages = agent._build_messages("新的问题", history)

        assert len(messages) == 4
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == "系统提示。"
        assert isinstance(messages[1], HumanMessage)
        assert messages[1].content == "之前的问题"
        assert isinstance(messages[2], AIMessage)
        assert messages[2].content == "之前的回答"
        assert isinstance(messages[3], HumanMessage)
        assert messages[3].content == "新的问题"


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
