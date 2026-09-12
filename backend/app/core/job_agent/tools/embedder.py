from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.embeddings import get_embeddings


@tool
async def job_embedder(text: str) -> dict:
    """Generate a vector embedding for job-related text.

    Uses SiliconFlow Qwen3-Embedding-8B to produce a 1024-dimensional
    embedding vector. Returns None on failure (graceful degradation).

    Args:
        text: The text to embed (e.g. job title + description).

    Returns:
        Dict with embedding (list[float] or None) and dimensions (int).
    """
    logger.info("Job embedder tool | text_len={}", len(text))

    if not text or not text.strip():
        return {"embedding": None, "dimensions": 0}

    try:
        embeddings = get_embeddings()
        vector = await embeddings.aembed_query(text)
        return {"embedding": vector, "dimensions": len(vector)}
    except Exception as e:
        logger.warning("Job embedding failed | error={}", e)
        return {"embedding": None, "dimensions": 0, "error": str(e)}
