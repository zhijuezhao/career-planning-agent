from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.agent.nodes import AgentState, call_model, execute_tools, should_continue

GRAPH_NODE_CALL_MODEL = "agent"
GRAPH_NODE_EXECUTE_TOOLS = "tools"


def build_agent_graph(
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
) -> StateGraph:
    """Build a standard ReAct agent loop graph.

    The graph has two nodes:
        - "agent": call the LLM (with tools bound).
        - "tools": execute tool calls.

    Edges:
        agent → tools (if tool calls present) → agent → ... → END.

    Args:
        llm: LLM with tools already bound via ``.bind_tools()``.
        tools: Tool list (used to build the ``tools_by_name`` lookup).

    Returns:
        An un-compiled ``StateGraph(AgentState)``.
    """
    graph = StateGraph(AgentState)

    graph.add_node(GRAPH_NODE_CALL_MODEL, call_model)
    graph.add_node(GRAPH_NODE_EXECUTE_TOOLS, execute_tools)

    graph.set_entry_point(GRAPH_NODE_CALL_MODEL)
    graph.add_conditional_edges(
        GRAPH_NODE_CALL_MODEL,
        should_continue,
        {"tools": GRAPH_NODE_EXECUTE_TOOLS, "end": END},
    )
    graph.add_edge(GRAPH_NODE_EXECUTE_TOOLS, GRAPH_NODE_CALL_MODEL)

    return graph


def compile_agent(
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Build and compile a ReAct agent graph.

    Convenience wrapper around ``build_agent_graph`` + ``.compile()``.

    Invoke with config to pass the LLM and tools:
        compiled.ainvoke(initial_state, {"configurable": {"llm": llm, "tools_by_name": tools_by_name}})

    Args:
        llm: LLM with tools already bound.
        tools: Tool list (used to build the lookup dict).

    Returns:
        A compiled ``CompiledStateGraph``.
    """
    return build_agent_graph(llm, tools).compile()


def build_agent(
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Alias for ``compile_agent``."""
    return compile_agent(llm, tools)
