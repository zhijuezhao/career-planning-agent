from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.resume_agent.embedding_text import build_portrait_text


@tool
async def profile_embedder(five_layers: dict) -> dict:
    """Generate a 1024-dim embedding vector from five-layer ability portrait.

    Args:
        five_layers: Dict with keys intention/traits/practice/soft_skills/hard_skills.

    Returns:
        Dict with content (str), embedding (list[float] or None on failure).
    """
    content = build_portrait_text(five_layers)
    if not content.strip():
        logger.warning("Empty portrait text, skipping embedding")
        return {"content": content, "embedding": None}

    try:
        from app.core.llm.embeddings import get_embeddings
        embeddings = get_embeddings()
        vector = await embeddings.aembed_query(content)
        logger.info("Embedding generated | dims={}", len(vector))
        return {"content": content, "embedding": vector}
    except Exception as exc:
        logger.warning("Embedding generation failed: {}", exc)
        return {"content": content, "embedding": None}
