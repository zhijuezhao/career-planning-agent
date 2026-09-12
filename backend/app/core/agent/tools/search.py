from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.rag.retriever import search_knowledge


@tool
async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web for career-related information.

    Uses the built-in career knowledge base. For real-time web search,
    configure a search API (e.g., SerpAPI, Tavily) and update this tool.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 5, max 10).

    Returns:
        Dict with results (list of {title, snippet, source}) and a note.
    """
    max_results = min(max(max_results, 1), 10)

    hits = await search_knowledge(query, top_k=max_results)

    results = []
    for hit in hits:
        results.append(
            {
                "title": hit["title"],
                "snippet": hit["content"][:300],
                "source": hit.get("category", "knowledge_base"),
            }
        )

    logger.info("Web search tool | query={!r:.60} | hits={}", query, len(results))

    return {
        "results": results,
        "note": "当前搜索基于本地知识库。如需实时网络搜索，请配置搜索 API（如 Tavily、SerpAPI）。",
    }
