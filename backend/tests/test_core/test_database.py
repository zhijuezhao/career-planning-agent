import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_connection():
    from app.infrastructure.database import engine
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_tables_exist():
    from app.infrastructure.database import engine
    expected_tables = {
        "users", "ability_profiles", "job_profiles", "job_raw_data",
        "chat_sessions", "chat_messages", "job_matches", "user_feedbacks",
        "growth_paths", "growth_plans", "career_reports", "ai_configs",
        "job_match_embeddings", "career_knowledge",
    }
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        actual_tables = {row[0] for row in result.fetchall()}
    await engine.dispose()
    missing = expected_tables - actual_tables
    assert not missing, f"Missing tables: {missing}"


@pytest.mark.asyncio
async def test_hnsw_indexes_exist():
    from app.infrastructure.database import engine
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexdef LIKE '%hnsw%'"
        ))
        indexes = {row[0] for row in result.fetchall()}
    await engine.dispose()
    assert "ix_job_match_embeddings_embedding" in indexes
    assert "ix_career_knowledge_embedding" in indexes


@pytest.mark.asyncio
async def test_users_table_constraints():
    from app.infrastructure.database import engine
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT conname, contype FROM pg_constraint "
            "WHERE conrelid = 'users'::regclass AND contype = 'u'"
        ))
        unique_constraints = {row[0] for row in result.fetchall()}
    await engine.dispose()
    assert "users_username_key" in unique_constraints
    assert "users_email_key" in unique_constraints


def test_all_models_importable():
    from app.domain.models import (
        AbilityProfile,
        AIConfig,
        CareerKnowledge,
        CareerReport,
        ChatMessage,
        ChatSession,
        GrowthPath,
        GrowthPlan,
        JobMatch,
        JobMatchEmbedding,
        JobProfile,
        JobRawData,
        User,
        UserFeedback,
    )
    models = [
        User, AbilityProfile, JobProfile, JobRawData,
        ChatSession, ChatMessage, JobMatch, UserFeedback,
        GrowthPath, GrowthPlan, CareerReport, AIConfig,
        JobMatchEmbedding, CareerKnowledge,
    ]
    assert len(models) == 14
    for m in models:
        assert hasattr(m, "__tablename__")


@pytest.mark.asyncio
async def test_alembic_version_exists():
    from app.infrastructure.database import engine
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = [row[0] for row in result.fetchall()]
    await engine.dispose()
    assert len(versions) == 1
