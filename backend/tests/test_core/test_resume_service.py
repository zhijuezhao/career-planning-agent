from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.skip(
    reason="旧表已删除（Task 1 删 AbilityProfile/CareerReport）；resume_service 引用已删模型，"
    "属死路径（旧 7-node 图已不运行），待对应任务清理"
)

try:
    from app.domain.services.resume_service import (
        save_career_report,
        save_user_match_embedding,
        update_resume_status,
        upsert_ability_profile,
    )
except ImportError:  # pragma: no cover
    save_career_report = None
    save_user_match_embedding = None
    update_resume_status = None
    upsert_ability_profile = None


@pytest.mark.asyncio
async def test_upsert_ability_profile_creates_new():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    five_layers = {
        "intention": {"target_position": ["后端开发"]},
        "traits": {"personality_tags": []},
        "practice": {},
        "soft_skills": {},
        "hard_skills": {},
    }

    profile = await upsert_ability_profile(mock_session, user_id=1, five_layers=five_layers)

    mock_session.add.assert_called_once()
    assert profile.user_id == 1
    assert profile.version == 1
    assert profile.intention == {"target_position": ["后端开发"]}


@pytest.mark.asyncio
async def test_upsert_ability_profile_updates_existing():
    existing = MagicMock()
    existing.id = 42
    existing.version = 3

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=mock_result)

    five_layers = {
        "intention": {"target_position": ["前端开发"]},
        "traits": {},
        "practice": {},
        "soft_skills": {},
        "hard_skills": {},
    }

    profile = await upsert_ability_profile(mock_session, user_id=1, five_layers=five_layers)

    mock_session.add.assert_not_called()
    assert profile.version == 4
    assert profile.intention == {"target_position": ["前端开发"]}


@pytest.mark.asyncio
async def test_save_user_match_embedding_with_vector():
    mock_session = AsyncMock()
    vector = [0.1] * 1024

    row = await save_user_match_embedding(
        mock_session, user_id=1, profile_id=42,
        content="test content", embedding=vector,
    )

    mock_session.add.assert_called_once()
    assert row is not None
    assert row.profile_id == 42


@pytest.mark.asyncio
async def test_save_user_match_embedding_skips_none():
    mock_session = AsyncMock()

    row = await save_user_match_embedding(
        mock_session, user_id=1, profile_id=42,
        content="test", embedding=None,
    )

    mock_session.add.assert_not_called()
    assert row is None


@pytest.mark.asyncio
async def test_save_career_report():
    mock_session = AsyncMock()

    report = await save_career_report(
        mock_session, user_id=1, profile_id=42,
        report_text="## 报告内容", target_job="后端开发",
    )

    mock_session.add.assert_called_once()
    assert report.report_content == {"text": "## 报告内容"}
    assert report.target_job == "后端开发"


@pytest.mark.asyncio
async def test_update_resume_status_success():
    mock_resume = MagicMock()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resume)

    await update_resume_status(
        mock_session, resume_id=1, status="done",
        profile_id=42, parsed_data={"name": "test"},
    )

    assert mock_resume.status == "done"
    assert mock_resume.profile_id == 42
    assert mock_resume.parsed_data == {"name": "test"}
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_resume_status_not_found():
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    await update_resume_status(mock_session, resume_id=999, status="failed")

    mock_session.flush.assert_not_called()
