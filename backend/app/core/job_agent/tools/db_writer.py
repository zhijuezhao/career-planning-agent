from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.domain.models.vector import JobMatchEmbedding
from app.domain.services.job_persist_service import upsert_job_profile, write_raw_job
from app.infrastructure.database import async_session_factory


async def _write_raw_data(data: dict) -> dict:
    """Insert a row into job_raw_data."""
    async with async_session_factory() as session:
        try:
            row = await write_raw_job(session, data)
            await session.commit()
            await session.refresh(row)
            logger.info("DB write: job_raw_data | id={} | title={!r:.40}", row.id, row.title)
            return {"success": True, "table": "job_raw_data", "record_id": row.id}
        except Exception as exc:
            await session.rollback()
            logger.warning("DB write failed: job_raw_data | error={}", exc)
            return {"success": False, "table": "job_raw_data", "record_id": None, "error": str(exc)}


async def _write_profile(data: dict) -> dict:
    """Insert or update a row in job_profiles（keyed by title）。

    B2-2 起：业务逻辑集中在 `job_persist_service.upsert_job_profile`，
    与导入流水线的 persist 阶段共用同一实现（含公司 upsert + `company_id` 关联）。
    """
    if not str(data.get("title") or "").strip():
        return {"success": False, "table": "job_profiles", "record_id": None, "error": "title is required"}

    async with async_session_factory() as session:
        try:
            profile, created = await upsert_job_profile(session, data)
            record_id = profile.id
            await session.commit()
            logger.info("DB write: job_profiles | id={} | title={!r:.40} | op={}",
                        record_id, profile.title, "insert" if created else "update")
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
    - 'job_profiles': Insert or update job profiles (keyed by title);
      B2-2 起会顺带 upsert `companies` 并把 `job_profiles.company_id` 挂上。
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
