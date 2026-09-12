from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rag.embeddings import aembed_query
from app.domain.models.vector import CareerKnowledge


async def search_knowledge(
    query: str,
    top_k: int = 5,
    category: str | None = None,
    max_distance: float | None = None,
    session: AsyncSession | None = None,
) -> list[dict]:
    """Search career_knowledge table by vector cosine distance.

    Args:
        query: Natural-language query text.
        top_k: Max number of results to return.
        category: Optional category filter.
        max_distance: Optional cosine-distance cutoff (lower = more similar).
        session: Optional injected session (for tests / callers owning a transaction).

    Returns:
        List of hits: {id, title, content, category, distance, metadata}.
    """
    if not query.strip():
        return []

    vector = await aembed_query(query)

    if session is not None:
        return await _search_in_session(session, query, vector, top_k, category, max_distance)

    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as owned_session:
        return await _search_in_session(owned_session, query, vector, top_k, category, max_distance)


async def _search_in_session(
    session: AsyncSession,
    query: str,
    vector: list[float],
    top_k: int,
    category: str | None,
    max_distance: float | None,
) -> list[dict]:
    distance_expr = CareerKnowledge.embedding.cosine_distance(vector)
    stmt = (
        select(CareerKnowledge, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(top_k)
    )
    if category:
        stmt = stmt.where(CareerKnowledge.category == category)

    rows = (await session.execute(stmt)).all()
    hits: list[dict] = []
    for knowledge, distance in rows:
        if max_distance is not None and float(distance) > max_distance:
            continue
        hits.append(
            {
                "id": knowledge.id,
                "title": knowledge.title,
                "content": knowledge.content,
                "category": knowledge.category,
                "distance": float(distance),
                "metadata": knowledge.metadata_,
            }
        )
    logger.info("Knowledge search | query={!r:.60} | hits={}", query, len(hits))
    return hits
