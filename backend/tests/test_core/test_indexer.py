from unittest.mock import AsyncMock, patch

import pytest
from app.core.rag.indexer import KnowledgeInput, index_knowledge
from app.domain.models.vector import CareerKnowledge
from sqlalchemy import select
from tests.conftest import test_session_factory

TEST_TITLE_PREFIX = "T15_TEST_INDEX"


async def cleanup_index_rows():
    from sqlalchemy import delete

    async with test_session_factory() as session:
        await session.execute(
            delete(CareerKnowledge).where(
                CareerKnowledge.title.like(f"{TEST_TITLE_PREFIX}%")
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_index_empty_list_returns_zero():
    result = await index_knowledge([])
    assert result == {"indexed": 0, "skipped": 0, "total": 0}


@pytest.mark.asyncio
async def test_index_new_items():
    fake_vector = [0.1] * 1024
    mock_embed = AsyncMock(return_value=[fake_vector])

    await cleanup_index_rows()
    try:
        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            async with test_session_factory() as session:
                result = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_NEW",
                            content="测试知识内容",
                            category="career",
                        )
                    ],
                    session=session,
                )

        assert result == {"indexed": 1, "skipped": 0, "total": 1}

        async with test_session_factory() as session:
            row = (
                await session.execute(
                    select(CareerKnowledge).where(
                        CareerKnowledge.title == f"{TEST_TITLE_PREFIX}_NEW"
                    )
                )
            ).scalar_one_or_none()
        assert row is not None
        assert row.content == "测试知识内容"
        assert row.category == "career"
        assert row.embedding is not None
    finally:
        await cleanup_index_rows()


@pytest.mark.asyncio
async def test_index_skip_duplicates():
    fake_vector = [0.2] * 1024
    mock_embed = AsyncMock(return_value=[fake_vector])

    await cleanup_index_rows()
    try:
        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            async with test_session_factory() as session:
                result1 = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_DUP",
                            content="原始内容",
                            category="career",
                        )
                    ],
                    session=session,
                )
                assert result1 == {"indexed": 1, "skipped": 0, "total": 1}

                result2 = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_DUP",
                            content="新内容(应被跳过)",
                            category="career",
                        )
                    ],
                    session=session,
                )
                assert result2 == {"indexed": 0, "skipped": 1, "total": 1}

        async with test_session_factory() as verify_session:
            row = (
                await verify_session.execute(
                    select(CareerKnowledge).where(
                        CareerKnowledge.title == f"{TEST_TITLE_PREFIX}_DUP"
                    )
                )
            ).scalar_one_or_none()
        assert row is not None
        assert row.content == "原始内容"
    finally:
        await cleanup_index_rows()


@pytest.mark.asyncio
async def test_index_batch_processing():
    fake_vectors = [[0.3] * 1024, [0.4] * 1024]
    mock_embed = AsyncMock(return_value=fake_vectors)

    await cleanup_index_rows()
    try:
        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            async with test_session_factory() as session:
                result = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_BATCH1",
                            content="批次1内容",
                            category="job",
                        ),
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_BATCH2",
                            content="批次2内容",
                            category="skill",
                        ),
                    ],
                    batch_size=2,
                    session=session,
                )

        assert result == {"indexed": 2, "skipped": 0, "total": 2}

        async with test_session_factory() as session:
            rows = (
                await session.execute(
                    select(CareerKnowledge).where(
                        CareerKnowledge.title.like(f"{TEST_TITLE_PREFIX}_BATCH%")
                    )
                )
            ).scalars().all()
        assert len(rows) == 2
    finally:
        await cleanup_index_rows()


@pytest.mark.asyncio
async def test_index_with_injected_session():
    fake_vector = [0.5] * 1024
    mock_embed = AsyncMock(return_value=[fake_vector])

    await cleanup_index_rows()
    try:
        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            async with test_session_factory() as session:
                result = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_INJECTED",
                            content="注入会话测试",
                            category="career",
                        )
                    ],
                    session=session,
                )

        assert result == {"indexed": 1, "skipped": 0, "total": 1}
    finally:
        await cleanup_index_rows()


@pytest.mark.asyncio
async def test_index_mixed_new_and_existing():
    mock_embed = AsyncMock()

    await cleanup_index_rows()
    try:
        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            mock_embed.return_value = [[0.6] * 1024]
            async with test_session_factory() as session:
                await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_MIXED_A",
                            content="已有记录",
                            category="career",
                        )
                    ],
                    session=session,
                )

        with patch("app.core.rag.indexer.aembed_texts", mock_embed):
            mock_embed.return_value = [[0.8] * 1024]
            async with test_session_factory() as session2:
                result = await index_knowledge(
                    [
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_MIXED_A",
                            content="应被跳过",
                            category="career",
                        ),
                        KnowledgeInput(
                            title=f"{TEST_TITLE_PREFIX}_MIXED_B",
                            content="新记录",
                            category="career",
                        ),
                    ],
                    session=session2,
                )

        assert result == {"indexed": 1, "skipped": 1, "total": 2}
    finally:
        await cleanup_index_rows()
