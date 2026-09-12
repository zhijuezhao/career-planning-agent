from unittest.mock import AsyncMock, patch

import pytest
from app.core.rag.embeddings import aembed_query, aembed_texts
from app.core.rag.retriever import search_knowledge
from app.domain.models.vector import CareerKnowledge
from sqlalchemy import delete
from tests.conftest import test_session_factory

TEST_TITLE_PREFIX = "T14_TEST_KNOWLEDGE"


def make_vector(seed: float) -> list[float]:
    return [seed if i % 50 == 0 else 0.0 for i in range(1024)]


async def seed_knowledge_row(title: str, vector: list[float], category: str = "career") -> int:
    async with test_session_factory() as session:
        row = CareerKnowledge(
            title=title,
            content="测试知识内容，描述岗位发展路径与技能要求。",
            category=category,
            embedding=vector,
        )
        session.add(row)
        await session.flush()
        row_id = row.id
        await session.commit()
        return row_id


async def cleanup_knowledge_rows():
    async with test_session_factory() as session:
        await session.execute(
            delete(CareerKnowledge).where(CareerKnowledge.title.like(f"{TEST_TITLE_PREFIX}%"))
        )
        await session.commit()


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty():
    mock_embed = AsyncMock(return_value=[])
    with patch("app.core.rag.retriever.aembed_query", mock_embed):
        hits = await search_knowledge("   ")

    assert hits == []
    mock_embed.assert_not_called()


@pytest.mark.asyncio
async def test_search_finds_exact_match_with_injected_session():
    target_title = f"{TEST_TITLE_PREFIX}_EXACT"
    await cleanup_knowledge_rows()
    try:
        target_vector = make_vector(0.5)
        target_id = await seed_knowledge_row(target_title, target_vector, category="career")

        mock_embed = AsyncMock(return_value=make_vector(0.5))
        with patch("app.core.rag.retriever.aembed_query", mock_embed):
            async with test_session_factory() as session:
                hits = await search_knowledge("前端开发岗位的知识", top_k=5, session=session)

        assert len(hits) >= 1
        top_hit = hits[0]
        assert top_hit["id"] == target_id
        assert top_hit["title"] == target_title
        assert top_hit["category"] == "career"
        assert top_hit["distance"] <= 0.001
        assert "content" in top_hit
    finally:
        await cleanup_knowledge_rows()


@pytest.mark.asyncio
async def test_search_category_filter_excludes_other_categories():
    await cleanup_knowledge_rows()
    try:
        target_vector = make_vector(0.5)
        await seed_knowledge_row(f"{TEST_TITLE_PREFIX}_JOB", target_vector, category="job")
        await seed_knowledge_row(f"{TEST_TITLE_PREFIX}_CAREER", target_vector, category="career")

        mock_embed = AsyncMock(return_value=make_vector(0.5))
        with patch("app.core.rag.retriever.aembed_query", mock_embed):
            async with test_session_factory() as session:
                hits = await search_knowledge("职业发展", category="job", session=session)

        assert len(hits) >= 1
        assert all(h["category"] == "job" for h in hits)
        assert all(h["title"].endswith("_JOB") for h in hits)
    finally:
        await cleanup_knowledge_rows()


@pytest.mark.asyncio
async def test_aembed_query_delegates_to_embeddings():
    fake_vector = [0.1] * 1024
    mock_embeddings = AsyncMock()
    mock_embeddings.aembed_query = AsyncMock(return_value=fake_vector)

    with patch("app.core.rag.embeddings.get_embeddings", return_value=mock_embeddings):
        result = await aembed_query("职业规划咨询")

    assert result == fake_vector
    mock_embeddings.aembed_query.assert_called_once_with("职业规划咨询")


@pytest.mark.asyncio
async def test_aembed_texts_batch():
    fake_vectors = [[0.1] * 1024, [0.2] * 1024]
    mock_embeddings = AsyncMock()
    mock_embeddings.aembed_documents = AsyncMock(return_value=fake_vectors)

    with patch("app.core.rag.embeddings.get_embeddings", return_value=mock_embeddings):
        result = await aembed_texts(["文本一", "文本二"])

    assert result == fake_vectors
    mock_embeddings.aembed_documents.assert_called_once_with(["文本一", "文本二"])


@pytest.mark.asyncio
async def test_aembed_texts_empty():
    result = await aembed_texts([])
    assert result == []


@pytest.mark.asyncio
async def test_search_max_distance_filters_far_rows():
    await cleanup_knowledge_rows()
    try:
        near_title = f"{TEST_TITLE_PREFIX}_NEAR"
        far_title = f"{TEST_TITLE_PREFIX}_FAR"
        await seed_knowledge_row(near_title, make_vector(0.5), category="career")
        await seed_knowledge_row(far_title, make_vector(-0.5), category="career")

        mock_embed = AsyncMock(return_value=make_vector(0.5))
        with patch("app.core.rag.retriever.aembed_query", mock_embed):
            async with test_session_factory() as session:
                hits = await search_knowledge(
                    "测试检索", max_distance=0.5, session=session
                )

        titles = [h["title"] for h in hits]
        assert near_title in titles
        assert far_title not in titles
    finally:
        await cleanup_knowledge_rows()
