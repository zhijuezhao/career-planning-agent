"""L2 模板仓库：落库前的校验、命中/未命中计数、自愈覆盖。

这里最关键的一条是 **`save_template` 必须拒绝脏表达式**：模板是**模型产出**的定位式，
落库等于把它持久化给未来所有导入使用 —— 脏表达式一旦进库，会在很久以后以
"某次导入莫名失败"的形式爆出来，那时已经很难联想到是几天/几周前某次学习写坏的。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.core.link_enrich.templates import load_templates, record_outcome, save_template
from app.domain.models.link_xpath_template import LinkXpathTemplate
from sqlalchemy import delete, select, text
from tests.conftest import test_session_factory

GOOD_XPATH = '//div[contains(concat(" ", normalize-space(@class), " "), \'job-salary\')]'
OTHER_XPATH = '//*[@id=\'salary-value\']'


@pytest.fixture
def domain() -> str:
    return f"z{uuid.uuid4().hex[:10]}.example.com"


@pytest.fixture(autouse=True)
def _clean():
    async def _run() -> None:
        async with test_session_factory() as session:
            await session.execute(delete(LinkXpathTemplate).where(LinkXpathTemplate.domain.like("z%")))
            await session.commit()

    asyncio.run(_run())
    yield
    asyncio.run(_run())


class TestSave:
    def test_saves_and_reads_back(self, domain):
        async def _run():
            async with test_session_factory() as session:
                assert await save_template(session, domain, "salary", GOOD_XPATH) is True
                await session.commit()
                assert await load_templates(session, domain) == {"salary": GOOD_XPATH}

        asyncio.run(_run())

    @pytest.mark.parametrize(
        "bad",
        ["//*[contains(., 'x')]", "//a | //b", "//div/following-sibling::div", "/html/body/div", ""],
    )
    def test_refuses_dirty_expressions(self, domain, bad):
        async def _run():
            async with test_session_factory() as session:
                assert await save_template(session, domain, "salary", bad) is False
                await session.commit()
                rows = (await session.execute(
                    select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
                )).scalars().all()
                assert rows == [], "脏表达式绝不能落库"

        asyncio.run(_run())

    def test_requires_a_domain(self):
        async def _run():
            async with test_session_factory() as session:
                assert await save_template(session, "", "salary", GOOD_XPATH) is False

        asyncio.run(_run())

    def test_second_save_overwrites_and_counts(self, domain):
        """自愈：站改版后模型学到新表达式 → 覆盖旧的，而不是留下两条。"""

        async def _run():
            async with test_session_factory() as session:
                await save_template(session, domain, "salary", GOOD_XPATH)
                await session.commit()
                await save_template(session, domain, "salary", OTHER_XPATH)
                await session.commit()

                rows = (await session.execute(
                    select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
                )).scalars().all()
                assert len(rows) == 1
                assert rows[0].xpath == OTHER_XPATH
                assert rows[0].hit_count == 2

        asyncio.run(_run())


class TestLoad:
    def test_unknown_domain_is_empty(self):
        async def _run():
            async with test_session_factory() as session:
                assert await load_templates(session, "never-seen.example.com") == {}

        asyncio.run(_run())

    def test_empty_domain_is_empty(self):
        async def _run():
            async with test_session_factory() as session:
                assert await load_templates(session, "") == {}

        asyncio.run(_run())

    def test_pre_existing_dirty_row_is_skipped_not_executed(self, domain):
        """库里若已有脏数据（历史遗留/人工改坏），读的时候要跳过而不是执行。"""

        async def _run():
            async with test_session_factory() as session:
                # 绕过 save 的校验直接塞一行（模拟历史脏数据）
                session.add(
                    LinkXpathTemplate(domain=domain, field="salary", xpath="//a | //b")
                )
                await session.commit()
                assert await load_templates(session, domain) == {}

        asyncio.run(_run())


class TestRecordOutcome:
    def test_hit_and_miss_counters(self, domain):
        async def _run():
            async with test_session_factory() as session:
                await save_template(session, domain, "salary", GOOD_XPATH)
                await session.commit()
                await record_outcome(session, domain, "salary", hit=True)
                await record_outcome(session, domain, "salary", hit=False)
                await record_outcome(session, domain, "salary", hit=False)
                await session.commit()

                row = (await session.execute(
                    select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
                )).scalar_one()
                assert row.hit_count == 2  # 1（save）+ 1（hit）
                assert row.miss_count == 2
                assert row.last_ok_at is not None

        asyncio.run(_run())

    def test_unknown_template_is_ignored(self, domain):
        async def _run():
            async with test_session_factory() as session:
                # 不该抛异常（记命中是观测行为，不是关键路径）
                await record_outcome(session, domain, "salary", hit=True)
                await record_outcome(session, "", "salary", hit=True)

        asyncio.run(_run())


def test_no_rows_left_behind():
    async def _run():
        async with test_session_factory() as session:
            assert (
                await session.execute(
                    text("SELECT count(*) FROM link_xpath_templates WHERE domain LIKE 'z%'")
                )
            ).scalar_one() == 0

    asyncio.run(_run())
