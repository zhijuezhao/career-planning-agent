from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import delete

from app.core.resume_agent.schemas import DimensionScoring
from app.domain.models.dimension_score import DimensionScore


async def write_dimension_scores(
    profile_type: str,
    profile_id: int,
    scoring: DimensionScoring,
    session,
) -> int:
    await session.execute(
        delete(DimensionScore).where(
            DimensionScore.profile_type == profile_type,
            DimensionScore.profile_id == profile_id,
        )
    )

    rows_created = 0
    for top_dim, sub_scores in scoring.dimensions.items():
        for sub_dim, score_val in sub_scores.sub_dimensions.items():
            row = DimensionScore(
                profile_type=profile_type,
                profile_id=profile_id,
                top_dimension=top_dim,
                sub_dimension=sub_dim,
                score=score_val,
            )
            session.add(row)
            rows_created += 1

    await session.flush()
    logger.info(
        "Wrote {} dimension scores | type={} | profile_id={}",
        rows_created, profile_type, profile_id,
    )
    return rows_created


@tool
async def score_deriver(
    dimension_scoring_dict: dict,
    profile_type: str,
    profile_id: int,
) -> dict:
    """Write dimension scores to the dimension_scores table.

    Args:
        dimension_scoring_dict: Dict representation of DimensionScoring from LLM parsing.
        profile_type: 'candidate' or 'job'.
        profile_id: ID of the ability_profiles or job_profiles row.

    Returns:
        Dict with rows_created count and total_dim_score.
    """
    scoring = DimensionScoring.model_validate(dimension_scoring_dict)

    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as session:
        try:
            rows = await write_dimension_scores(profile_type, profile_id, scoring, session)
            await session.commit()
            return {
                "rows_created": rows,
                "total_dim_score": scoring.total_dim_score,
                "profile_type": profile_type,
                "profile_id": profile_id,
            }
        except Exception:
            await session.rollback()
            raise
