"""B2-2 / B2-5 / P2 单元/集成测试：公司 upsert、岗位↔公司关联、导入批量落库（真实 dev DB）。

范围：
    * `normalise_company_name` 纯函数规则；
    * `upsert_company` 幂等 + 只在空字段时补全；
    * `upsert_job_profile` 挂 company_id、维护 job_count、空值不覆盖已有画像；
    * **B2-5**：同一岗位名多家公司 → 关联与计数；关联幂等（hit_count 累加）、
      `backfill_links_from_profiles` 幂等；
    * **P2（2026-09-26）**：去重粒度 `(岗位名, 公司)` —— 同名不同公司 2 条画像、
      归一化合并大小写/空白、无公司画像被首家已知公司"收养"、唯一索引在 DB 层兜底；
    * `persist_import_rows` 的统计与**行级容错**（一行没 title 不该拖垮其他行）。

所有用例只创建 `b22_<ts>_*` 前缀的数据，结束时按前缀 + 自增 id 精确清理。
"""

from __future__ import annotations

import time

import pytest
from app.core.dedup_keys import normalise_title
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
from sqlalchemy.exc import IntegrityError
from tests.conftest import test_session_factory

_PREFIX = f"b22_{int(time.time())}"


def _title(name: str) -> str:
    return f"{_PREFIX}_{name}"


def _company(name: str) -> str:
    return f"{_PREFIX}_{name}"


async def _cleanup() -> None:
    """按前缀删除本模块创建的公司/岗位/原始行（顺序：先解绑再删公司）。

    岗位用 `lower(btrim(title))` 匹配：P2 的归一化用例会写入大小写/前后空白不同的
    标题变体，普通 `LIKE 'b22_%'` 会漏掉带前后空格的那些。
    """
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE lower(btrim(title)) LIKE :p"),
            {"p": f"{_PREFIX.lower()}%"},
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE lower(btrim(title)) LIKE :p"),
            {"p": f"{_PREFIX.lower()}%"},
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
    """B2-5 + P2：岗位 ↔ 公司。

    ⚠️ **P2（2026-09-26）改了粒度**：去重键从「只看岗位名」变成 `(岗位名, 公司)`。
    所以"同一岗位名被两家公司招"**不再是**"1 条画像 + 2 条关联"，而是
    **2 条画像**（每家一条，各自 `company_id`）。B2-5 的能力在**读**这一侧保留：
    管理端 `company_count` / 「在招公司」按 `title_key` 汇总同名画像（见 `test_admin_companies.py`）。
    """

    async def test_same_title_two_companies_makes_two_profiles(self):
        title = _title("同岗多公司")
        async with test_session_factory() as session:
            profile_a, created_a = await upsert_job_profile(
                session, {"title": title, "company": _company("甲公司X")}
            )
            company_a_id = profile_a.company_id
            profile_b, created_b = await upsert_job_profile(
                session, {"title": title, "company": _company("乙公司X")}
            )
            await session.commit()

            # P2：两条独立画像，各挂各的公司
            assert created_a is True and created_b is True
            assert profile_b.id != profile_a.id
            assert profile_b.company_id != company_a_id
            assert profile_a.title_key == profile_b.title_key

            # 每条画像各自一条关联行（关联表仍记录来源与命中次数）
            for profile in (profile_a, profile_b):
                links = list(
                    (
                        await session.execute(
                            select(JobCompanyLink).where(
                                JobCompanyLink.job_profile_id == profile.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(links) == 1
                assert links[0].company_id == profile.company_id

            # 两家公司各自「有多少岗位」都是 1
            for name in ("甲公司X", "乙公司X"):
                company = (
                    await session.execute(select(Company).where(Company.name == _company(name)))
                ).scalar_one()
                assert company.job_count == 1
                assert await company_job_count(session, company.id) == 1

    async def test_title_normalisation_merges_case_and_whitespace(self):
        """P2：`java 开发` / `Java 开发` / 前后多空格视为同一个岗位（忽略大小写 + 折叠空白）。"""
        base = _title("归一化  岗位")  # 双空格
        tight = _title("归一化 岗位")  # 单空格 → 折叠后同一个 key
        async with test_session_factory() as session:
            first, created_first = await upsert_job_profile(
                session, {"title": base, "company": _company("归一化公司")}
            )
            await session.commit()
            assert created_first is True
            # 关键不变量：DB 生成列与 Python 归一化**必须给出一致的键**
            # （三处规则：dedup_keys.normalise_title / job_profiles.title_key 生成列 / apply_ddl.py 的 DDL）
            assert first.title_key == normalise_title(base)
            assert first.title_key == normalise_title(tight)
            assert first.title_key != base  # 生成列确实做了归一化（折叠了双空格）

            for variant in (base.upper(), f"  {base}  ", tight):
                again, created = await upsert_job_profile(
                    session, {"title": variant, "company": _company("归一化公司")}
                )
                await session.commit()
                assert created is False, variant
                assert again.id == first.id, variant

    async def test_company_unknown_profile_is_adopted_by_first_known_company(self):
        """P2：**公司未知 ≠ 另一家公司**。

        用户的真实路径是"先导职业路线表（无公司列）→ 再导含公司表"。
        若把"未知公司"当成另一家，同一个岗位会裂成两条（一条永远没有公司）。
        这里的规则是：含公司数据首次出现时**收养**那条"公司未知"的画像。
        """
        title = _title("收养岗位")
        async with test_session_factory() as session:
            unknown, created_unknown = await upsert_job_profile(session, {"title": title})
            await session.commit()
            assert created_unknown is True and unknown.company_id is None

            adopted, created_adopted = await upsert_job_profile(
                session, {"title": title, "company": _company("收养公司"), "industry": "互联网"}
            )
            await session.commit()

            assert created_adopted is False  # 收养而非新建
            assert adopted.id == unknown.id
            assert adopted.company_id is not None
            assert adopted.industry == "互联网"

            total = (
                await session.execute(
                    select(func.count()).select_from(JobProfile).where(JobProfile.title == title)
                )
            ).scalar_one()
            assert total == 1

            # 收养之后再出现第二家公司 → 这时才新建第二条
            second, created_second = await upsert_job_profile(
                session, {"title": title, "company": _company("收养公司二")}
            )
            await session.commit()
            assert created_second is True
            assert second.id != adopted.id

    async def test_unknown_company_row_does_not_fork_existing_profile(self):
        """P2：已有"带公司"的画像时，再来一行**不带公司**的同名行不应裂出第二条。"""
        title = _title("不回退岗位")
        async with test_session_factory() as session:
            known, created_known = await upsert_job_profile(
                session, {"title": title, "company": _company("不回退公司")}
            )
            await session.commit()
            assert created_known is True

            again, created_again = await upsert_job_profile(
                session, {"title": title, "summary": "无公司行的补充摘要"}
            )
            await session.commit()

            assert created_again is False
            assert again.id == known.id
            assert again.summary == "无公司行的补充摘要"
            assert again.company_id == known.company_id  # 公司归属不被抹掉

    async def test_unique_index_blocks_manual_duplicate(self):
        """P2：`(title_key, company_id)` 由 DB 唯一索引兜底 —— 绕过服务层直插也会被拦。"""
        title = _title("唯一索引岗位")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("唯一索引公司")}
            )
            await session.commit()
            key = profile.title_key

        async with test_session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO job_profiles (title, company_id) VALUES (:t, :c)"
                    ),
                    {"t": f"  {title.upper()}  ", "c": profile.company_id},
                )
            await session.rollback()

        # NULL 公司也照样唯一（NULLS NOT DISTINCT）
        async with test_session_factory() as session:
            await session.execute(
                text("INSERT INTO job_profiles (title) VALUES (:t)"),
                {"t": _title("NULL公司唯一")},
            )
            await session.commit()
        async with test_session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text("INSERT INTO job_profiles (title) VALUES (:t)"),
                    {"t": _title("null公司唯一").upper()},
                )
            await session.rollback()
        assert key

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
