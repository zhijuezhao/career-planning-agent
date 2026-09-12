from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger


@tool
async def match_jobs(
    user_id: int,
    profile_id: int,
    top_k: int = 5,
) -> dict:
    """Search and match jobs for a user based on their ability profile.

    Args:
        user_id: The user's ID.
        profile_id: The ability profile ID.
        top_k: Number of top matches to return (default 5).

    Returns:
        Dict with match results or error message.
    """
    try:
        import sqlalchemy

        from app.core.matching import match_user_to_jobs
        from app.domain.models.resume import UserMatchEmbedding
        from app.infrastructure.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                sqlalchemy.select(UserMatchEmbedding).where(
                    UserMatchEmbedding.user_id == user_id,
                    UserMatchEmbedding.profile_id == profile_id,
                )
            )
            embedding = result.scalar_one_or_none()
            if not embedding:
                return {"error": "User profile embedding not found. Please generate profile embedding first."}

            matches = await match_user_to_jobs(
                user_id=user_id,
                profile_id=profile_id,
                user_vector=embedding.embedding,
                top_k=top_k,
                max_distance=0.5,
                session=session,
            )

            return {
                "success": True,
                "total": len(matches),
                "matches": [
                    {
                        "job_profile_id": m["job_profile_id"],
                        "match_score": m["match_score"],
                        "analysis": m.get("analysis", {}),
                    }
                    for m in matches
                ],
            }
    except Exception as exc:
        logger.error("match_jobs tool error | user_id={} | error={}", user_id, exc)
        return {"error": f"Job matching failed: {exc}"}
