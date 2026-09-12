import pytest
from app.core.resume_agent.schemas import SUB_DIMENSIONS, DimensionScoring
from app.core.resume_agent.tools.score_deriver import (
    score_deriver,
    write_dimension_scores,
)
from app.domain.models.dimension_score import DimensionScore
from sqlalchemy import delete, select
from tests.conftest import test_session_factory


def _make_scoring_dict(total: float = 3.4) -> dict:
    return {
        "profile_type": "candidate",
        "total_dim_score": total,
        "dimensions": {
            dim: {"score": 3.0, "sub_dimensions": {sub: 3.0 for sub in subs}}
            for dim, subs in SUB_DIMENSIONS.items()
        },
    }


@pytest.mark.asyncio
async def test_write_dimension_scores_creates_13_rows():
    scoring = DimensionScoring.model_validate(_make_scoring_dict())
    async with test_session_factory() as session:
        try:
            rows = await write_dimension_scores("candidate", 99999, scoring, session)
            assert rows == 13
            result = await session.execute(
                select(DimensionScore).where(
                    DimensionScore.profile_type == "candidate",
                    DimensionScore.profile_id == 99999,
                )
            )
            db_rows = result.scalars().all()
            assert len(db_rows) == 13
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_write_dimension_scores_upsert_replaces_old():
    scoring1 = DimensionScoring.model_validate(_make_scoring_dict(total=2.0))
    scoring2 = DimensionScoring.model_validate(_make_scoring_dict(total=4.0))

    async with test_session_factory() as session:
        await write_dimension_scores("candidate", 88888, scoring1, session)
        await session.commit()

    async with test_session_factory() as session:
        await write_dimension_scores("candidate", 88888, scoring2, session)
        await session.commit()

    async with test_session_factory() as session:
        result = await session.execute(
            select(DimensionScore).where(
                DimensionScore.profile_type == "candidate",
                DimensionScore.profile_id == 88888,
            )
        )
        db_rows = result.scalars().all()
        assert len(db_rows) == 13

    async with test_session_factory() as session:
        await session.execute(
            delete(DimensionScore).where(DimensionScore.profile_id == 88888)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_tool_ainvoke_writes_to_db():
    scoring_dict = _make_scoring_dict()
    result = await score_deriver.ainvoke({
        "dimension_scoring_dict": scoring_dict,
        "profile_type": "candidate",
        "profile_id": 77777,
    })

    assert result["rows_created"] == 13
    assert result["total_dim_score"] == 3.4
    assert result["profile_type"] == "candidate"

    async with test_session_factory() as session:
        await session.execute(
            delete(DimensionScore).where(DimensionScore.profile_id == 77777)
        )
        await session.commit()
