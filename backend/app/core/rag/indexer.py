from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rag.embeddings import aembed_texts
from app.domain.models.vector import CareerKnowledge


@dataclass
class KnowledgeInput:
    title: str
    content: str
    category: str | None = None
    metadata: dict | None = field(default_factory=dict)


async def index_knowledge(
    items: list[KnowledgeInput],
    batch_size: int = 10,
    session: AsyncSession | None = None,
) -> dict[str, int]:
    """Index knowledge items into the career_knowledge table.

    Items whose title already exists in the table are skipped (idempotent).
    Embedding is generated in batches via SiliconFlow.

    Args:
        items: Knowledge items to index.
        batch_size: Number of items to embed per batch.
        session: Optional injected session (for tests / callers owning a transaction).

    Returns:
        Stats dict: {indexed, skipped, total}.
    """
    if not items:
        return {"indexed": 0, "skipped": 0, "total": 0}

    if session is not None:
        return await _index_in_session(session, items, batch_size)

    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as owned_session:
        return await _index_in_session(owned_session, items, batch_size)


async def _index_in_session(
    session: AsyncSession,
    items: list[KnowledgeInput],
    batch_size: int,
) -> dict[str, int]:
    """Core indexing logic — runs inside a session context."""
    titles = [item.title for item in items]

    existing = (
        await session.execute(
            select(CareerKnowledge.title).where(CareerKnowledge.title.in_(titles))
        )
    ).scalars().all()
    existing_set = set(existing)

    new_items = [item for item in items if item.title not in existing_set]
    skipped = len(items) - len(new_items)

    indexed = 0
    for i in range(0, len(new_items), batch_size):
        batch = new_items[i : i + batch_size]
        texts = [item.content for item in batch]
        vectors = await aembed_texts(texts)

        rows = [
            CareerKnowledge(
                title=item.title,
                content=item.content,
                category=item.category,
                embedding=vector,
                metadata_=item.metadata,
            )
            for item, vector in zip(batch, vectors, strict=True)
        ]
        session.add_all(rows)
        await session.flush()
        indexed += len(rows)
        logger.info(
            "Indexed batch | start={} | size={} | total_indexed={}",
            i,
            len(batch),
            indexed,
        )

    await session.commit()
    logger.info(
        "Indexing complete | indexed={} | skipped={} | total={}",
        indexed,
        skipped,
        len(items),
    )
    return {"indexed": indexed, "skipped": skipped, "total": len(items)}
