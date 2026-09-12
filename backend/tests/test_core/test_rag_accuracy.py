"""RAG accuracy regression tests using the golden test set.

These tests verify that the RAG retriever returns the expected
knowledge entries for a set of predefined queries. The embedding
vectors are mocked so the tests are deterministic and do not
require real API calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.core.rag.retriever import search_knowledge
from app.domain.models.vector import CareerKnowledge
from loguru import logger
from sqlalchemy import delete
from tests.conftest import test_session_factory
from tests.golden_test_set.test_cases import (
    GOLDEN_KNOWLEDGE_ENTRIES,
    GOLDEN_TEST_CASES,
    NOISE_SEED,
)

GOLDEN_TITLE_PREFIX = "GOLDEN_TEST"

TOTAL_CASES = len(GOLDEN_TEST_CASES)
TOTAL_ENTRIES = len(GOLDEN_KNOWLEDGE_ENTRIES)


def make_vector(seed: float) -> list[float]:
    """Create a 1024-dim vector with a distinctive pattern from the seed."""
    return [seed if i % 50 == 0 else 0.0 for i in range(1024)]


async def seed_golden_knowledge() -> None:
    """Insert all golden knowledge entries into the test DB."""
    async with test_session_factory() as session:
        for entry in GOLDEN_KNOWLEDGE_ENTRIES:
            row = CareerKnowledge(
                title=f"{GOLDEN_TITLE_PREFIX}_{entry['title']}",
                content=entry["content"],
                category=entry["category"],
                embedding=make_vector(entry["seed"]),
            )
            session.add(row)
        await session.commit()


async def cleanup_golden_knowledge() -> None:
    """Remove all golden test entries from the DB."""
    async with test_session_factory() as session:
        await session.execute(
            delete(CareerKnowledge).where(
                CareerKnowledge.title.like(f"{GOLDEN_TITLE_PREFIX}%")
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_all_golden_cases_recall_at_k():
    """Run ALL golden test cases and verify recall@K.

    This is the main regression test: for each case, patch the embedding
    query so the retriever 'sees' the expected vector, then check that
    all expected titles appear in the results.
    """
    await cleanup_golden_knowledge()
    await seed_golden_knowledge()

    passed = 0
    failed_cases: list[str] = []

    try:
        for case in GOLDEN_TEST_CASES:
            mock_embed = AsyncMock(return_value=make_vector(case.query_seed))

            with patch("app.core.rag.retriever.aembed_query", mock_embed):
                async with test_session_factory() as session:
                    hits = await search_knowledge(
                        case.query,
                        top_k=case.min_top_k,
                        category=case.category,
                        session=session,
                    )

            hit_titles = {h["title"] for h in hits}
            expected_prefixed = {f"{GOLDEN_TITLE_PREFIX}_{t}" for t in case.expected_titles}
            missing = expected_prefixed - hit_titles

            if missing:
                failed_cases.append(
                    f"  Query: {case.query!r}\n"
                    f"  Description: {case.description}\n"
                    f"  Missing: {missing}\n"
                    f"  Got titles: {hit_titles}\n"
                )
                logger.warning(
                    "Golden test FAILED | query={!r} | missing={}",
                    case.query,
                    missing,
                )
            else:
                passed += 1
                logger.info(
                    "Golden test PASSED | query={!r} | hits={}",
                    case.query,
                    len(hits),
                )

    finally:
        await cleanup_golden_knowledge()

    # Summary
    logger.info(
        "Golden test results | passed={}/{} | failed={}",
        passed,
        TOTAL_CASES,
        TOTAL_CASES - passed,
    )

    if failed_cases:
        pytest.fail(
            f"{len(failed_cases)}/{TOTAL_CASES} golden test cases failed:\n"
            + "\n".join(failed_cases)
        )


@pytest.mark.asyncio
async def test_golden_knowledge_entries_count():
    """Verify the golden test set has the expected number of entries."""
    assert TOTAL_ENTRIES >= 5, "At least 5 knowledge entries are needed for meaningful tests"
    assert TOTAL_CASES >= 5, "At least 5 test cases are needed for meaningful tests"


@pytest.mark.asyncio
async def test_search_with_noise_entries():
    """Verify that noise entries do not pollute category-filtered results."""
    await cleanup_golden_knowledge()
    await seed_golden_knowledge()
    try:
        # Add a noise entry with a different category
        async with test_session_factory() as session:
            noise = CareerKnowledge(
                title=f"{GOLDEN_TITLE_PREFIX}_NOISE",
                content="这是噪声数据，不应该影响正常检索结果。",
                category="other",
                embedding=make_vector(NOISE_SEED),
            )
            session.add(noise)
            await session.commit()

        mock_embed = AsyncMock(return_value=make_vector(0.10))
        with patch("app.core.rag.retriever.aembed_query", mock_embed):
            async with test_session_factory() as session:
                hits = await search_knowledge(
                    "前端开发",
                    category="skill",
                    session=session,
                )

        titles = [h["title"] for h in hits]
        assert all(f"{GOLDEN_TITLE_PREFIX}_NOISE" not in t for t in titles)
        assert any(f"{GOLDEN_TITLE_PREFIX}_前端开发技能要求" in t for t in titles)
    finally:
        await cleanup_golden_knowledge()


@pytest.mark.asyncio
async def test_search_different_queries_return_different_results():
    """Verify that different queries return meaningfully different results."""
    await cleanup_golden_knowledge()
    await seed_golden_knowledge()
    try:
        mock_embed_1 = AsyncMock(return_value=make_vector(0.10))
        mock_embed_2 = AsyncMock(return_value=make_vector(0.60))

        with patch("app.core.rag.retriever.aembed_query", mock_embed_1):
            async with test_session_factory() as session:
                hits_1 = await search_knowledge("前端开发", top_k=3, session=session)

        with patch("app.core.rag.retriever.aembed_query", mock_embed_2):
            async with test_session_factory() as session:
                hits_2 = await search_knowledge("IT行业趋势", top_k=3, session=session)

        titles_1 = [h["title"] for h in hits_1]
        titles_2 = [h["title"] for h in hits_2]

        # The two queries should return different primary results
        assert titles_1 != titles_2, "Different queries should return different results"
        assert any("前端开发" in t for t in titles_1), "Frontend query should return frontend results"
        assert any("IT" in t or "行业" in t for t in titles_2), (
            "IT query should return IT results"
        )
    finally:
        await cleanup_golden_knowledge()
