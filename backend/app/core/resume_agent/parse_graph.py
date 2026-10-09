from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.core.resume_agent.graph import node_extract_pdf, node_map_layers, node_parse_resume


class ParseState(TypedDict):
    resume_id: int
    file_path: str
    raw_text: str
    page_count: int
    truncated: bool
    parsed_resume: dict[str, Any]
    five_layers: dict[str, Any]
    dimension_scoring: dict[str, Any]
    status: str
    error: str | None


def build_parse_graph():
    """解析-only 图：extract_pdf → parse_resume → map_layers。
    - 无 write_scores：六维分数在 node_parse_resume 已由 LLM 得出（state["dimension_scoring"]），
      候选行落库挪到快照生成（Task 4，用 write_dimension_scores）。
    - 无 embed/generate/persist：embedding 在快照生成（Task 4）时按冻结的 five_layers 计算。
    """
    g = StateGraph(ParseState)
    g.add_node("extract_pdf", node_extract_pdf)
    g.add_node("parse_resume", node_parse_resume)
    g.add_node("map_layers", node_map_layers)
    g.set_entry_point("extract_pdf")
    g.add_edge("extract_pdf", "parse_resume")
    g.add_edge("parse_resume", "map_layers")
    g.add_edge("map_layers", END)
    return g.compile()


async def parse_resume_only(file_path: str, resume_id: int) -> dict[str, Any]:
    """解析 PDF → 返回 {five_layers, dimension_scoring, parsed_resume}。不落任何库。"""
    graph = build_parse_graph()
    state = {"resume_id": resume_id, "file_path": file_path}
    out = await graph.ainvoke(state)
    return {
        "five_layers": out.get("five_layers"),
        "dimension_scoring": out.get("dimension_scoring"),
        "parsed_resume": out.get("parsed_resume"),
    }
