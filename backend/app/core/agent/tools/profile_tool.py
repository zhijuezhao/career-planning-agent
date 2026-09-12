from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import select

from app.domain.models.profile import AbilityProfile


@tool
async def get_user_profile(
    user_id: int,
    direction_tag: str = "default",
) -> dict:
    """Retrieve a user's ability profile by user ID and direction tag.

    The profile contains five-layer ability portrait data:
    intention, traits, practice, soft_skills, hard_skills.

    Args:
        user_id: The user's ID.
        direction_tag: Profile direction tag (default: "default").

    Returns:
        Dict with profile fields or null if not found.
    """
    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as session:
        stmt = select(AbilityProfile).where(
            AbilityProfile.user_id == user_id,
            AbilityProfile.direction_tag == direction_tag,
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

    if profile is None:
        logger.info("Profile not found | user_id={} | direction_tag={}", user_id, direction_tag)
        return {"profile": None, "message": "未找到该用户的能力画像，请先上传简历进行分析。"}

    profile_data = {
        "id": profile.id,
        "user_id": profile.user_id,
        "direction_tag": profile.direction_tag,
        "version": profile.version,
        "intention": profile.intention,
        "traits": profile.traits,
        "practice": profile.practice,
        "soft_skills": profile.soft_skills,
        "hard_skills": profile.hard_skills,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    logger.info(
        "Profile retrieved | user_id={} | direction_tag={} | version={}",
        user_id,
        direction_tag,
        profile.version,
    )
    return {"profile": profile_data}
