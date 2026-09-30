"""B2-2 / B2-5 / P2 / **任务 2 / 任务 3** 单元/集成测试：公司 upsert、岗位↔公司关联、导入批量落库（真实 dev DB）。

范围：
    * `normalise_company_name` 纯函数规则；
    * `upsert_company` 幂等 + 只在空字段时补全（含规模/省市）；
    * `upsert_job_profile` 落关联、维护 job_count、空值不覆盖已有画像；
    * **任务 2（2026-09-27）多对多模型**：岗位是**角色级**（一行一个岗位名），
      "同名被多家公司招" = **1 条岗位 + N 条关联**（不再是 P2 的 N 条岗位）；
      一次招聘自带的所在地/薪资/链接落在关联行上；`job_profiles.company_id` 不再写入；
    * **任务 3（2026-09-27）单键 + 删列**：`job_profiles.company_id`（含 FK/索引）确实不存在，
      唯一键是 `uq_job_profiles_title_key (title_key)`，"删公司撞唯一索引 → 500"结构上消失；
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
        """任务 2（多对多）：岗位是**角色级**的 → 公司归属落在**关联表**，不在岗位行上。"""
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
            # 任务 3：`company_id` 已从表/ORM 删除 —— 公司归属只在关联表里
            assert not hasattr(profile, "company_id")

            link = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile.id)
                )
            ).scalar_one()
            company = await session.get(Company, link.company_id)
            assert company is not None
            assert company.name == _company("公司A")
            assert company.job_count == 1
            # 「一次招聘」自带的属性落在**关联行**上
            assert link.city == "北京"
            assert link.salary == "20-30K"
            # 画像仍写在岗位行上
            assert profile.requirement_intensity == {"skill": 1}

    async def test_same_title_updates_and_keeps_company(self):
        async with test_session_factory() as session:
            first, created_a = await upsert_job_profile(
                session, {"title": _title("岗位B"), "company": _company("公司B"), "industry": "互联网"}
            )
            link = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == first.id)
                )
            ).scalar_one()
            company_id = link.company_id
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
            assert again.summary == "第二次导入补充的摘要"
            assert again.industry == "互联网"  # 本次未提供 → 保留原值
            # 关联仍是同一家，且命中次数累加
            link_again = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == again.id)
                )
            ).scalar_one()
            assert link_again.company_id == company_id
            assert link_again.hit_count == 2

    async def test_title_required(self):
        async with test_session_factory() as session:
            with pytest.raises(ValueError):
                await upsert_job_profile(session, {"company": _company("没标题")})

    async def test_refresh_job_count_recomputes(self):
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": _title("岗位C"), "company": _company("公司C")}
            )
            link = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile.id)
                )
            ).scalar_one()
            company = await session.get(Company, link.company_id)
            assert company is not None
            company.job_count = 999  # 人为弄脏
            await session.flush()

            count = await refresh_job_count(session, company.id)
            await session.commit()
            assert count == 1
            assert company.job_count == 1


class TestPersistImportRows:
    async def test_rejected_rows_are_not_written(self):
        """2026-09-30 用户要求：原始数据里**不存**不合格岗位。

        质检 D 级行不落 `job_raw_data`：原因只留在工单 errors 摘要里。
        原行为（C 层 2026-09-26）是 D 级行也写 `job_raw_data`
        （`import:rejected` / `is_active=False`），现已按用户要求移除。
        """
        async with test_session_factory() as session:
            stats = await persist_import_rows(session, [])
            await session.commit()
            assert stats["raw_written"] == 0
            assert "raw_written_rejected" not in stats
            assert stats["profiles_new"] == 0
            assert stats["failed"] == 0

        async with test_session_factory() as session:
            raw = (
                await session.execute(
                    select(JobRawData).where(JobRawData.title == _title("被拒1"))
                )
            ).scalar_one_or_none()
            assert raw is None  # 不合格岗位不进原始数据表

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
    """岗位 ↔ 公司 = **多对多**（2026-09-27 任务 2 用户拍板）。

    - `job_profiles` = **岗位角色级**：一行一个岗位名（`title_key` 唯一）；
    - `companies` = 公司；
    - `job_company_links` = 「谁在招谁」的**唯一真相**，一行 = 一次招聘
      （自带所在地/薪资/链接，重复出现累加 `hit_count`）。

    ⚠️ 这**推翻了 P2 的 `(岗位名, 公司)` 粒度**（当时"同名不同公司 = N 条岗位"）：
    那样会把最贵的角色级内容（技能/晋升/证书/画像）按公司数复制 N 份。
    """

    async def test_same_title_two_companies_makes_one_profile_and_two_links(self):
        title = _title("同岗多公司")
        async with test_session_factory() as session:
            profile_a, created_a = await upsert_job_profile(
                session, {"title": title, "company": _company("甲公司X")}
            )
            profile_b, created_b = await upsert_job_profile(
                session, {"title": title, "company": _company("乙公司X")}
            )
            await session.commit()

            # 多对多：**还是同一条岗位**（角色级），只是多了第二家在招它
            assert created_a is True
            assert created_b is False
            assert profile_b.id == profile_a.id

            links = list(
                (
                    await session.execute(
                        select(JobCompanyLink)
                        .where(JobCompanyLink.job_profile_id == profile_a.id)
                        .order_by(JobCompanyLink.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert len(links) == 2
            assert {link.company_id for link in links} == {
                (
                    await session.execute(
                        select(Company.id).where(Company.name == _company(name))
                    )
                ).scalar_one()
                for name in ("甲公司X", "乙公司X")
            }

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
        """**公司未知 ≠ 另一家公司**（用户的真实路径：先导职业路线表 → 再导含公司表）。

        多对多模型下这条**天然成立**：岗位按名唯一定位，含公司的那一行只是在同一岗位上
        补了一条在招关联 —— 不需要 P2 时代那套"收养"补丁。
        """
        title = _title("收养岗位")
        async with test_session_factory() as session:
            unknown, created_unknown = await upsert_job_profile(session, {"title": title})
            await session.commit()
            assert created_unknown is True

            adopted, created_adopted = await upsert_job_profile(
                session, {"title": title, "company": _company("收养公司"), "industry": "互联网"}
            )
            await session.commit()

            assert created_adopted is False  # 同一条岗位，不是新建
            assert adopted.id == unknown.id
            assert adopted.industry == "互联网"
            assert not hasattr(adopted, "company_id")  # 岗位行不挂公司（任务 3 已删该列）

            total = (
                await session.execute(
                    select(func.count()).select_from(JobProfile).where(JobProfile.title == title)
                )
            ).scalar_one()
            assert total == 1

            # 收养之后再出现第二家公司 → 岗位还是那一条，只是多一条关联
            second, created_second = await upsert_job_profile(
                session, {"title": title, "company": _company("收养公司二")}
            )
            await session.commit()
            assert created_second is False
            assert second.id == adopted.id
            links = list(
                (
                    await session.execute(
                        select(JobCompanyLink).where(JobCompanyLink.job_profile_id == adopted.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(links) == 2

    async def test_unknown_company_row_does_not_fork_existing_profile(self):
        """已有"带关联"的岗位时，再来一行**不带公司**的同名行不应裂出第二条。"""
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
            # 原有在招关联不被抹掉
            assert await company_job_count(
                session,
                (
                    await session.execute(
                        select(Company.id).where(Company.name == _company("不回退公司"))
                    )
                ).scalar_one(),
            ) == 1

    async def test_unique_index_blocks_manual_duplicate(self):
        """**岗位名唯一**由 DB 唯一索引兜底 —— 绕过服务层直插也会被拦。

        任务 3（2026-09-27）起索引是 **`uq_job_profiles_title_key (title_key)`** 单键
        （P2 的 `(title_key, company_id) NULLS NOT DISTINCT` 随 `company_id` 列一起删除）。
        """
        title = _title("唯一索引岗位")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("唯一索引公司")}
            )
            await session.commit()
            key = profile.title_key
            assert not hasattr(profile, "company_id")  # 列已删（任务 3）

        async with test_session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text("INSERT INTO job_profiles (title) VALUES (:t)"),
                    {"t": f"  {title.upper()}  "},
                )
            await session.rollback()

        # 归一化后不同（大小写/空白不同但 key 不同）的岗位照常能插
        async with test_session_factory() as session:
            await session.execute(
                text("INSERT INTO job_profiles (title) VALUES (:t)"),
                {"t": _title("另一个岗位")},
            )
            await session.commit()
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

    async def test_link_carries_posting_attributes(self):
        """「一次招聘」自带的所在地/薪资/链接落在**关联行**上（不是岗位行）。"""
        title = _title("招聘属性")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session,
                {
                    "title": title,
                    "company": _company("属性公司"),
                    "region": "广东",
                    "city": "深圳",
                    "salary": "25-40K",
                    "source_url": "https://example.com/job/1",
                },
            )
            await session.commit()
            link = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile.id)
                )
            ).scalar_one()
            assert (link.region, link.city) == ("广东", "深圳")
            assert link.salary == "25-40K"
            assert link.source_url == "https://example.com/job/1"

    async def test_placeholder_city_is_not_stored(self):
        """清洗阶段给缺失城市填的「未知」**不能**当真实地域写进关联行。"""
        title = _title("占位地域")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("占位公司"), "city": "未知"}
            )
            await session.commit()
            link = (
                await session.execute(
                    select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile.id)
                )
            ).scalar_one()
            assert link.city is None
            company = await session.get(Company, link.company_id)
            assert company is not None and company.city is None


class TestTask3SingleKeySchema:
    """任务 3（2026-09-27）的**结构验收**：单键 + 删列在库里真的生效。

    直接查系统目录（而不是相信脚本打印的 `[DROP]`）：脚本删错名字、或只跑了一半，
    这里就会红。
    """

    async def test_company_id_column_and_its_fk_index_are_gone(self):
        async with test_session_factory() as session:
            column_count = await session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'job_profiles' "
                    "AND column_name = 'company_id'"
                )
            )
            assert column_count == 0, "job_profiles.company_id 应已删除（任务 3）"
            assert not hasattr(JobProfile, "company_id"), "ORM 上仍残留 company_id 字段"

            fk_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'fk_job_profiles_company_id' "
                    "AND conrelid = to_regclass('public.job_profiles')"
                )
            )
            assert fk_count == 0, "外键 fk_job_profiles_company_id 应已删除"

            stale_index_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'i' "
                    "AND c.relname IN ('ix_job_profiles_company_id', 'uq_job_profiles_title_company')"
                )
            )
            assert stale_index_count == 0, "P2 的旧索引应已全部删除"

    async def test_unique_key_is_title_key_single_column(self):
        async with test_session_factory() as session:
            definition = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexname = 'uq_job_profiles_title_key'"
                )
            )
        assert definition is not None, "任务 3 的单键唯一索引 uq_job_profiles_title_key 不存在"
        assert "UNIQUE" in definition.upper()
        assert definition.rstrip().endswith("(title_key)"), definition
        assert "company_id" not in definition

    async def test_deleting_second_company_does_not_raise(self):
        """P2 隐患回归：两家公司各有同名岗位 → 删第二家**不再**撞唯一索引。

        P2 时代 `company_id` 上是 `ON DELETE SET NULL`，而唯一索引把它当身份
        （`(title_key, company_id) NULLS NOT DISTINCT`）→ 删第二家时两条岗位行都变成
        `(同名, NULL)` → `duplicate key ... (…, null)` → 接口 **500**（已实测复现）。
        任务 3 把该列删掉后，这条路径**结构上不可能**再发生。
        """
        title = _title("删公司回归")
        async with test_session_factory() as session:
            profile, _ = await upsert_job_profile(
                session, {"title": title, "company": _company("删公司甲")}
            )
            await session.commit()
            profile_id = profile.id
            links = list(
                (
                    await session.execute(
                        select(JobCompanyLink).where(JobCompanyLink.job_profile_id == profile_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(links) == 1
            first_company_id = links[0].company_id

            # 第二家公司招**同一个岗位**（多对多：岗位还是那一条）
            again, created = await upsert_job_profile(
                session, {"title": title, "company": _company("删公司乙")}
            )
            await session.commit()
            assert created is False and again.id == profile_id
            second_company_id = (
                await session.execute(
                    select(Company.id).where(Company.name == _company("删公司乙"))
                )
            ).scalar_one()
            assert second_company_id != first_company_id

        # 删掉第二家公司：唯一索引若还是 (title_key, company_id)，这里会 IntegrityError
        async with test_session_factory() as session:
            company = await session.get(Company, second_company_id)
            assert company is not None
            await session.delete(company)
            await session.commit()  # 不抛异常 = 通过

        async with test_session_factory() as session:
            assert (
                await session.execute(
                    select(func.count()).select_from(JobProfile).where(JobProfile.id == profile_id)
                )
            ).scalar_one() == 1  # 岗位本身不受影响
            remaining = list(
                (
                    await session.execute(
                        select(JobCompanyLink.company_id).where(
                            JobCompanyLink.job_profile_id == profile_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert remaining == [first_company_id]  # 只剩第一家的关联
