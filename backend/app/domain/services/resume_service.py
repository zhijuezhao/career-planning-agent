from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.profile import AbilityProfile
from app.domain.models.report import CareerReport
from app.domain.models.resume import Resume, UserMatchEmbedding


async def upsert_ability_profile(
    session: AsyncSession,
    user_id: int,
    five_layers: dict,
    direction_tag: str = "default",
) -> AbilityProfile:
    stmt = select(AbilityProfile).where(
        AbilityProfile.user_id == user_id,
        AbilityProfile.direction_tag == direction_tag,
    )
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = AbilityProfile(
            user_id=user_id,
            direction_tag=direction_tag,
            intention=five_layers.get("intention", {}),
            traits=five_layers.get("traits", {}),
            practice=five_layers.get("practice", {}),
            soft_skills=five_layers.get("soft_skills", {}),
            hard_skills=five_layers.get("hard_skills", {}),
            version=1,
        )
        session.add(profile)
    else:
        profile.intention = five_layers.get("intention", {})
        profile.traits = five_layers.get("traits", {})
        profile.practice = five_layers.get("practice", {})
        profile.soft_skills = five_layers.get("soft_skills", {})
        profile.hard_skills = five_layers.get("hard_skills", {})
        profile.version += 1

    await session.flush()
    logger.info(
        "AbilityProfile upserted | user_id={} | profile_id={} | version={}",
        user_id, profile.id, profile.version,
    )
    return profile


async def save_user_match_embedding(
    session: AsyncSession,
    user_id: int,
    profile_id: int,
    content: str,
    embedding: list[float] | None,
) -> UserMatchEmbedding | None:
    if embedding is None:
        logger.warning("Skipping embedding save | profile_id={} | embedding is None", profile_id)
        return None

    row = UserMatchEmbedding(
        user_id=user_id,
        profile_id=profile_id,
        content=content,
        embedding=embedding,
    )
    session.add(row)
    await session.flush()
    logger.info("UserMatchEmbedding saved | profile_id={}", profile_id)
    return row


async def save_career_report(
    session: AsyncSession,
    user_id: int,
    profile_id: int,
    report_text: str,
    target_job: str | None = None,
) -> CareerReport:
    row = CareerReport(
        user_id=user_id,
        profile_id=profile_id,
        target_job=target_job,
        report_content={"text": report_text},
        version=1,
    )
    session.add(row)
    await session.flush()
    logger.info("CareerReport saved | profile_id={}", profile_id)
    return row


async def update_resume_status(
    session: AsyncSession,
    resume_id: int,
    status: str,
    profile_id: int | None = None,
    error_message: str | None = None,
    parsed_data: dict | None = None,
    raw_text: str | None = None,
    page_count: int | None = None,
) -> None:
    resume = await session.get(Resume, resume_id)
    if resume is None:
        logger.error("Resume not found for status update | id={}", resume_id)
        return

    resume.status = status
    if profile_id is not None:
        resume.profile_id = profile_id
    if error_message is not None:
        resume.error_message = error_message
    if parsed_data is not None:
        resume.parsed_data = parsed_data
    if raw_text is not None:
        resume.raw_text = raw_text
    if page_count is not None:
        resume.page_count = page_count

    await session.flush()
    logger.info("Resume status updated | id={} | status={}", resume_id, status)
