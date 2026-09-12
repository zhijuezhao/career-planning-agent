from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import select

from app.domain.models.job import JobProfile, JobRawData
from app.domain.models.vector import JobMatchEmbedding
from app.infrastructure.database import async_session_factory


async def _write_raw_data(data: dict) -> dict:
    """Insert a row into job_raw_data."""
    async with async_session_factory() as session:
        try:
            row = JobRawData(
                title=data.get("title", ""),
                company=data.get("company"),
                city=data.get("city"),
                salary=data.get("salary"),
                industry=data.get("industry"),
                description=data.get("description"),
                requirements=data.get("requirements"),
                source=data.get("source", "import"),
                is_active=data.get("is_active", True),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("DB write: job_raw_data | id={} | title={!r:.40}", row.id, row.title)
            return {"success": True, "table": "job_raw_data", "record_id": row.id}
        except Exception as exc:
            await session.rollback()
            logger.warning("DB write failed: job_raw_data | error={}", exc)
            return {"success": False, "table": "job_raw_data", "record_id": None, "error": str(exc)}


async def _write_profile(data: dict) -> dict:
    """Insert or update a row in job_profiles.

    Uses title as the dedup key: if a profile with the same title exists,
    updates it; otherwise creates a new one.
    """
    title = data.get("title", "")
    if not title:
        return {"success": False, "table": "job_profiles", "record_id": None, "error": "title is required"}

    async with async_session_factory() as session:
        try:
            # Check existing profile by title
            result = await session.execute(
                select(JobProfile).where(JobProfile.title == title).limit(1)
            )
            existing = result.scalar_one_or_none()

            # Build portrait fields from nested data
            five_dim = data.get("five_dimensions") or {}
            outlook = data.get("outlook") or {}
            career_paths = data.get("career_paths") or []
            transition_roles = data.get("transition_roles") or []

            if existing:
                existing.industry = data.get("industry", existing.industry)
                existing.level = data.get("level", existing.level)
                existing.hard_skills = data.get("hard_skills", existing.hard_skills)
                existing.soft_skills = data.get("soft_skills", existing.soft_skills)
                existing.salary_range = data.get("salary", existing.salary_range)
                existing.education_requirement = data.get("education_requirement", existing.education_requirement)
                existing.experience_requirement = data.get("experience_requirement", existing.experience_requirement)
                existing.career_path = career_paths if career_paths else existing.career_path
                existing.transition_paths = transition_roles if transition_roles else existing.transition_paths
                existing.requirement_intensity = five_dim if five_dim else existing.requirement_intensity
                existing.outlook = outlook if outlook else existing.outlook
                existing.summary = data.get("summary", existing.summary)
                record_id = existing.id
            else:
                profile = JobProfile(
                    title=title,
                    industry=data.get("industry"),
                    level=data.get("level"),
                    hard_skills=data.get("hard_skills"),
                    soft_skills=data.get("soft_skills"),
                    salary_range=data.get("salary"),
                    education_requirement=data.get("education_requirement"),
                    experience_requirement=data.get("experience_requirement"),
                    career_path=career_paths or None,
                    transition_paths=transition_roles or None,
                    requirement_intensity=five_dim or None,
                    outlook=outlook or None,
                    summary=data.get("summary"),
                )
                session.add(profile)
                await session.flush()
                record_id = profile.id

            await session.commit()
            logger.info("DB write: job_profiles | id={} | title={!r:.40} | op={}",
                        record_id, title, "update" if existing else "insert")
            return {"success": True, "table": "job_profiles", "record_id": record_id}
        except Exception as exc:
            await session.rollback()
            logger.warning("DB write failed: job_profiles | error={}", exc)
            return {"success": False, "table": "job_profiles", "record_id": None, "error": str(exc)}


async def _write_embedding(data: dict) -> dict:
    """Insert a row into job_match_embeddings.

    Requires job_profile_id and content. Embedding vector is optional.
    """
    profile_id = data.get("job_profile_id")
    content = data.get("content", "")

    if not profile_id or not content:
        return {
            "success": False, "table": "job_match_embeddings",
            "record_id": None,
            "error": "job_profile_id and content are required",
        }

    async with async_session_factory() as session:
        try:
            embedding_vec = data.get("embedding")
            row = JobMatchEmbedding(
                job_profile_id=profile_id,
                content=content,
                embedding=embedding_vec,
                metadata_=data.get("metadata"),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("DB write: job_match_embeddings | id={} | profile_id={}", row.id, profile_id)
            return {"success": True, "table": "job_match_embeddings", "record_id": row.id}
        except Exception as exc:
            await session.rollback()
            logger.warning("DB write failed: job_match_embeddings | error={}", exc)
            return {"success": False, "table": "job_match_embeddings", "record_id": None, "error": str(exc)}


_TABLE_DISPATCH = {
    "job_raw_data": _write_raw_data,
    "job_profiles": _write_profile,
    "job_match_embeddings": _write_embedding,
}


@tool
async def db_writer(
    table: str,
    data: dict,
) -> dict:
    """Write job-related data to the database.

    Inserts or updates records in job-related tables:
    - 'job_raw_data': Insert cleaned/imported job rows.
    - 'job_profiles': Insert or update job profiles (keyed by title).
    - 'job_match_embeddings': Insert embedding vectors for job profiles.

    Args:
        table: Target table name ('job_raw_data', 'job_profiles',
               'job_match_embeddings').
        data: Record data as a dict. Fields vary by table:
            - job_raw_data: title, company, city, salary, industry,
              description, requirements, source
            - job_profiles: title, industry, salary, hard_skills,
              soft_skills, five_dimensions, outlook, summary,
              career_paths, transition_roles, career_paths
            - job_match_embeddings: job_profile_id, content, embedding,
              metadata

    Returns:
        Dict with success (bool), table (str), record_id (int or None),
        and optional error (str).
    """
    logger.info("DB writer tool | table={} | data_keys={}", table, list(data.keys()))

    handler = _TABLE_DISPATCH.get(table)
    if handler is None:
        valid = list(_TABLE_DISPATCH.keys())
        return {
            "success": False,
            "table": table,
            "record_id": None,
            "error": f"Unknown table '{table}'. Valid: {valid}",
        }

    return await handler(data)
