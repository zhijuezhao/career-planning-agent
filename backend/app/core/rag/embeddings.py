from __future__ import annotations

from loguru import logger

from app.core.llm.embeddings import get_embeddings

__all__ = ["get_embeddings", "aembed_texts", "aembed_query"]


async def aembed_query(query: str) -> list[float]:
    embeddings = get_embeddings()
    vector = await embeddings.aembed_query(query)
    logger.info("Query embedded | dims={}", len(vector))
    return vector


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    embeddings = get_embeddings()
    vectors = await embeddings.aembed_documents(texts)
    logger.info("Documents embedded | count={} | dims={}", len(texts), len(vectors[0]) if vectors else 0)
    return vectors
