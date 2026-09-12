from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.rag.retriever import search_knowledge


@tool
async def career_knowledge_search(
    query: str,
    top_k: int = 5,
    category: str | None = None,
) -> dict:
    """Search the career knowledge base for relevant information.

    Uses vector similarity search to find career-related knowledge entries
    (industry trends, job requirements, skill development paths, etc.).

    Args:
        query: Natural-language search query (e.g., "前端开发需要什么技能").
        top_k: Maximum number of results to return (default 5, max 20).
        category: Optional category filter (e.g., "career", "job", "skill").

    Returns:
        Dict with hits (list of {id, title, content, category, distance, metadata}).
    """
    top_k = min(max(top_k, 1), 20)

    hits = await search_knowledge(query, top_k=top_k, category=category)

    logger.info("Knowledge search tool | query={!r:.60} | hits={}", query, len(hits))
    return {"hits": hits}
