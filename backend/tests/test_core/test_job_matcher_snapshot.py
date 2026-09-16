"""Task 5: match_user_to_jobs reads snapshot embedding + frozen six-dim scores.

Offline (no DB): the per-hit loop makes MULTIPLE session.execute calls
(search, job industry, job dims, weights), so execute uses an explicit
side_effect list instead of one shared MagicMock.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.matching import match_user_to_jobs
from app.domain.models.profile_snapshot import ProfileSnapshot


def _snap(dims=None, embedding=None, sid=1, uid=1, pid=1):
    return ProfileSnapshot(
        id=sid,
        user_id=uid,
        profile_id=pid,
        embedding=embedding if embedding is not None else [0.1] * 1024,
        six_dim_scores_json=dims if dims is not None else {"专业技术能力": 4.0, "团队协作": 3.5},
        form_raw_json={},
        five_layers_json={},
    )


@pytest.mark.asyncio
async def test_match_uses_snapshot_embedding_and_frozen_scores():
    snap = _snap()
    mock_session = AsyncMock()

    # Call 1: vector search -> one job hit.
    hit = MagicMock(job_profile_id=10, content="x")
    search_result = MagicMock()
    search_result.all.return_value = [(hit, 0.2)]

    # Call 2: job industry -> "技术研发岗".
    ind_result = MagicMock()
    ind_result.scalar_one_or_none.return_value = "技术研发岗"

    # Call 3: job dimension scores (DimensionScore job rows) -> one dimension.
    score = MagicMock(top_dimension="专业技术能力", sub_dimension="专业技术能力", score=4.0)
    scores_result = MagicMock()
    scores_result.scalars.return_value.all.return_value = [score]

    # Call 4: dimension weights for the job industry -> weight for the dim.
    weight = MagicMock(top_dimension="专业技术能力", weight=1.0)
    weights_result = MagicMock()
    weights_result.scalars.return_value.all.return_value = [weight]

    mock_session.execute = AsyncMock(side_effect=[search_result, ind_result, scores_result, weights_result])

    results = await match_user_to_jobs(1, snap, top_k=5, session=mock_session)

    assert len(results) == 1
    assert results[0]["job_profile_id"] == 10
    assert results[0]["distance"] == 0.2
    assert "match_score" in results[0]
    analysis = results[0]["analysis"]
    assert "vector_similarity" in analysis
    # Frozen scores flow into the dimension-matches analysis.
    assert analysis["dimension_matches"]["专业技术能力"]["user_score"] == 4.0


@pytest.mark.asyncio
async def test_match_weights_follow_job_industry():
    """R-5.1: each candidate's weights come from ITS OWN industry, per-hit."""
    snap = _snap(dims={"专业技术能力": 4.0})
    mock_session = AsyncMock()

    hit = MagicMock(job_profile_id=10, content="x")
    search_result = MagicMock()
    search_result.all.return_value = [(hit, 0.3)]

    # The candidate job's industry must drive the weights query.
    ind_result = MagicMock()
    ind_result.scalar_one_or_none.return_value = "互联网"

    score = MagicMock(top_dimension="专业技术能力", sub_dimension="专业技术能力", score=4.0)
    scores_result = MagicMock()
    scores_result.scalars.return_value.all.return_value = [score]

    weight = MagicMock(top_dimension="专业技术能力", weight=0.7)
    weights_result = MagicMock()
    weights_result.scalars.return_value.all.return_value = [weight]

    mock_session.execute = AsyncMock(side_effect=[search_result, ind_result, scores_result, weights_result])

    results = await match_user_to_jobs(1, snap, top_k=5, session=mock_session)

    assert len(results) == 1
    assert results[0]["analysis"]["weights_used"]["专业技术能力"] == 0.7


@pytest.mark.asyncio
async def test_search_uses_snapshot_embedding_not_topk_times_three():
    """match_user_to_jobs searches by snapshot.embedding with top_k passed through (R-5.3)."""
    from unittest.mock import patch

    vec = [0.42] * 1024
    snap = _snap(embedding=vec)
    mock_session = AsyncMock()

    with patch("app.core.matching.job_matcher.search_jobs_by_vector", new_callable=AsyncMock) as m:
        # No hits -> loop body never runs.
        m.return_value = []
        results = await match_user_to_jobs(1, snap, top_k=5, session=mock_session)
        assert results == []
        args, kwargs = m.call_args
        assert args[0] == vec
        assert kwargs["top_k"] == 5
        assert kwargs["session"] is mock_session


@pytest.mark.asyncio
async def test_zero_embedding_returns_empty():
    """R-5.6: an all-zero 1024-vector is treated as no-match (no NaN ranking)."""
    snap = _snap(embedding=[0.0] * 1024)
    mock_session = AsyncMock()

    results = await match_user_to_jobs(1, snap, top_k=5, session=mock_session)

    assert results == []
    assert not mock_session.execute.called