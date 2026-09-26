"""B2-2 / B2-5 单元/集成测试：公司 upsert、岗位↔公司关联、导入批量落库（真实 dev DB）。

范围：
    * `normalise_company_name` 纯函数规则；
    * `upsert_company` 幂等 + 只在空字段时补全；
    * `upsert_job_profile` 挂 company_id、维护 job_count、空值不覆盖已有画像；
    * **B2-5**：同一岗位名多家公司 → 关联表两条、主公司不漂移、双方 job_count 正确；
      关联幂等（hit_count 累加）、`backfill_links_from_profiles` 幂等;
    * `persist_import_rows` 的统计与**行级容错**（一行没 title 不该拖垮其他行）。

所有用例只创建 `b22_<ts>_*` 前缀的数据，结束时按前缀 + 自增 id 精确清理。
"""

from __future__ import annotations

import time

import pytest
from app.domain.models.company import Company
from app.domain.models.job import JobProfile, JobRawData
from app.domain.models.job_company_link import JobCompanyLink
from app.domain.services.company_service import (
    backfill_links_from_profiles,
    company_job_count,
    normalise_company_name,
    refresh_job_count,
    upsert_company,
)
from app.domain.services.job_persist_service import (
    persist_import_rows,
    upsert_job_profile,
    write_raw_job,
)
from sqlalchemy import func, select, text
from tests.conftest import test_session_factory

_PREFIX = f"b22_{int(time.time())}"


def _title(name: str) -> str:
    return f"{_PREFIX}_{name}"


def _company(name: str) -> str:
    return f"{_PREFIX}_{name}"


async def _cleanup() -> None:
    """按前缀删除本模块创建的公司/岗位/原始行（顺序：先解绑再删公司）。"""
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.commit()


@pytest.fixture(autouse=True)
def clean_b22_rows():
    import asyncio

    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


class TestNormaliseCompanyName:
    def test_collapses_whitespace(self):
        assert normalise_company_name("  A  科技有限公司 ") == "A 科技有限公司"

    def test_placeholder_values_become_none(self):
        for value in (None, "", "   ", "nan", "NaN", "未知", "保密", "-"):
            assert normalise_company_name(value) is None, value

    def test_truncates_to_column_limit(self):
        assert len(normalise_company_name("x" * 300) or "") == 200

    def test_keeps_normal_name(self):
        assert normalise_company_name("字节跳动") == "字节跳动"


class TestUpsertCompany:
    async def test_idempotent_by_name(self):
        async with test_session_factory() as session:
            first = await upsert_company(session, _company("同一家"), industry="互联网", city="北京")
            second = await upsert_company(session, _company("同一家"))
            await session.commit()

            assert first is not None and second is not None
            assert first.id == second.id
            count = (
                await session.execute(
                    select(func.count()).select_from(Company).where(Company.name == _company("同一家"))
                )
            ).scalar_one()
            assert count == 1

    async def test_blank_fields_are_not_overwritten(self):
        async with test_session_factory() as session:
            company = await upsert_company(session, _company("不可覆盖"), industry="互联网", city="北京")
            assert company is not None
            await session.commit()

            again = await upsert_company(session, _company("不可覆盖"), industry="金融", city="上海")
            await session.commit()
            assert again is not None
            assert again.industry == "互联网"  # 人工修正过的值不被导入覆盖
            assert again.city == "北京"

    async def test_placeholder_name_returns_none(self):
        async with test_session_factory() as session:
            assert await upsert_company(session, "未知") is None
            assert await upsert_company(session, None) is None


class TestUpsertJobProfile:
    async def test_creates_profile_with_company_and_count(self):
        async with test_session_factory() as session:
            profile, created = await upsert_job_profile(
                session,
                {
                    "title": _title("岗位A"),
                    "company": _company("公司A"),
                    "industry": "互联网",
                    "city": "北京",
                    "salary": "20-30K",
                    "five_dimensions": {"skill": 1},
                },
            )
            await session.commit()

            assert created is True
            assert profile.company_id is not None

            company = await session.get(Company, profile.company_id)
            assert company is not None
            assert company.name == _company("公司A")
            assert company.job_count == 1

    async def test_same_title_updates_and_keeps_company(self):
        async with test_session_factory() as session:
            first, created_a = await upsert_job_profile(
                session, {"title": _title("岗位B"), "company": _company("公司B"), "industry": "互联网"}
            )
            company_id = first.company_id
            await session.commit()

            again, created_b = await upsert_job_profile(
                session,
                {
                    "title": _title("岗位B"),
                    "company": _company("公司B"),
                    "summary": "第二次导入补充的摘要",
                },
            )
            await session.commit()

            assert created_a is True and created_b is False
            assert again.id == first.id
            assert again.company_id == company_id
            assert again.summary == "第二次导入补充的摘要"
            assert again.industry == "互联网"  # 本次未提供 → 保留原值

    async def test_title_required(self):
        async with test_session_factory() as session:
            with pytest.raises(ValueError):
                await upsert_job_profile(session, {"company": _company("没标题")})

    async def test_refresh_job_count_recomputes(self):
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": _title("岗位C"), "company": _company("公司C")}
            )
            company = await session.get(Company, profile.company_id)
            assert company is not None
            company.job_count = 999  # 人为弄脏
            await session.flush()

            count = await refresh_job_count(session, company.id)
            await session.commit()
            assert count == 1
            assert company.job_count == 1


class TestPersistImportRows:
    async def test_rejected_rows_are_archived_as_raw_only(self):
        """C 层：质检 D 级行**也落 `job_raw_data`**（`import:rejected` / `is_active=False`），
        但不生成画像 —— 目的是"不丢数据"，以后可离线重加工而不必重新上传。

        背景：2026-09-26 实测 84 条里 81 条被判 D，此前在库里**毫无痕迹**。
        """
        rejected = [{"title": _title("被拒1"), "requirements": "核心技能：Java、Spring"}]

        async with test_session_factory() as session:
            stats = await persist_import_rows(session, [], rejected_rows=rejected)
            await session.commit()
            assert stats["raw_written"] == 0
            assert stats["raw_written_rejected"] == 1
            assert stats["profiles_new"] == 0
            assert stats["failed"] == 0

        async with test_session_factory() as session:
            raw = (
                await session.execute(
                    select(JobRawData).where(JobRawData.title == _title("被拒1"))
                )
            ).scalar_one()
            assert raw.source == "import:rejected"
            assert raw.is_active is False
            assert "Java" in (raw.requirements or "")

            profile = (
                await session.execute(
                    select(JobProfile).where(JobProfile.title == _title("被拒1"))
                )
            ).scalar_one_or_none()
            assert profile is None  # D 级不生成画像

    async def test_stats_and_per_row_tolerance(self):
        rows = [
            {"title": _title("批量1"), "company": _company("批量公司"), "city": "北京"},
            {"title": _title("批量2"), "company": _company("批量公司"), "city": "上海"},
            {"company": _company("批量公司")},  # 没 title → 该行失败
        ]
        async with test_session_factory() as session:
            stats = await persist_import_rows(session, rows)
            await session.commit()

            assert stats["raw_written"] == 2
            assert stats["profiles_new"] == 2
            assert stats["failed"] == 1
            assert stats["errors"] and "title is required" in stats["errors"][0]

        async with test_session_factory() as session:
            # 成功的两行真的落库了；公司 job_count = 2
            titles = (
                await session.execute(
                    select(JobProfile.title).where(JobProfile.title.like(f"{_PREFIX}_批量%"))
                )
            ).scalars().all()
            assert len(titles) == 2
            company = (
                await session.execute(
                    select(Company).where(Company.name == _company("批量公司"))
                )
            ).scalar_one()
            assert company.job_count == 2

    async def test_raw_rows_written_with_source(self):
        async with test_session_factory() as session:
            await write_raw_job(
                session,
                {"title": _title("原始行"), "company": _company("原始公司"), "source": "import"},
            )
            await session.commit()

            row = (
                await session.execute(
                    select(JobRawData).where(JobRawData.title == _title("原始行"))
                )
            ).scalar_one()
            assert row.company == _company("原始公司")
            assert row.source == "import"


class TestJobCompanyLinks:
    """B2-5：岗位 ↔ 公司 多对多（同一岗位可被多家公司招）。"""

    async def test_same_title_two_companies_keeps_both_links(self):
        title = _title("同岗多公司")
        async with test_session_factory() as session:
            profile_a, created_a = await upsert_job_profile(
                session, {"title": title, "company": _company("甲公司X")}
            )
            primary_company_id = profile_a.company_id
            profile_b, created_b = await upsert_job_profile(
                session, {"title": title, "company": _company("乙公司X")}
            )
            await session.commit()

            # 画像仍按 title 去重
            assert created_a is True and created_b is False
            assert profile_b.id == profile_a.id
            # 主公司首次为准，不被后来者覆盖
            assert profile_b.company_id == primary_company_id

            links = list(
                (
                    await session.execute(
                        select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile_a.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(links) == 2

            # 两家公司各自「有多少岗位」都是 1
            for name in ("甲公司X", "乙公司X"):
                company = (
                    await session.execute(select(Company).where(Company.name == _company(name)))
                ).scalar_one()
                assert company.job_count == 1
                assert await company_job_count(session, company.id) == 1

    async def test_link_is_idempotent_and_counts_hits(self):
        title = _title("重复导入")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("重复公司")}
            )
            await upsert_job_profile(session, {"title": title, "company": _company("重复公司")})
            await upsert_job_profile(session, {"title": title, "company": _company("重复公司")})
            await session.commit()

            links = list(
                (
                    await session.execute(
                        select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(links) == 1
            assert links[0].hit_count == 3

    async def test_backfill_links_from_profiles_is_idempotent(self):
        """老数据只有 company_id 没有关联行 → sync 回填一次；重复调用不再新建。"""
        title = _title("老数据岗位")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("老数据公司")}
            )
            # 模拟 B2-5 之前的数据：删掉关联，只留 company_id
            await session.execute(
                text("DELETE FROM job_company_links WHERE job_profile_id = :i"),
                {"i": profile.id},
            )
            await session.commit()

            first = await backfill_links_from_profiles(session)
            await session.commit()
            assert first >= 1

            second = await backfill_links_from_profiles(session)
            await session.commit()
            assert second == 0

            count = (
                await session.execute(
                    select(func.count())
                    .select_from(JobCompanyLink)
                    .where(JobCompanyLink.job_profile_id == profile.id)
                )
            ).scalar_one()
            assert count == 1
