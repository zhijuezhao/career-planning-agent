"""岗位侧六维**读画像**的测试（P5 2026-09-27）。

背景（这条链原来是断的）：匹配引擎岗位侧原先读 `dimension_scores` 表里
`profile_type='job'` 的行，而**全仓没有任何地方写那种行**（唯一真实写入者写的是
`candidate`）→ 岗位侧恒为 `{}` → `compute_match_score` 把"取不到分"当"无要求=满匹配"
→ 六维对比**完全没参与**。现在改为读画像 `job_profiles.requirement_intensity`。

本文件钉住两件事：
1. **取值器**：形状容错、只认六维规范名、缺的维度不补 0；
2. **刻意不映射**：旧口径的英文五维（technical/…）**不许**被翻译成中文六维
   —— 两套维度含义不一一对应，硬映射就是**编数据**（用户 2026-09-27 明确否掉）。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.core.dimensions.rubrics import DIMENSION_ORDER
from app.domain.services.job_persist_service import upsert_job_profile
from app.domain.services.job_query_service import (
    extract_job_dimensions,
    job_dimension_scores,
)
from sqlalchemy import text
from tests.conftest import test_session_factory

_PREFIX = f"jobdims_{int(time.time())}"

#: 一份"标准形状"的六维画像（`{维度: {score, key_skills?}}`）
_PORTRAIT = {
    "专业技术能力": {"score": 5, "key_skills": ["Java", "Spring"]},
    "实践经验背景": {"score": 4},
    "通用软素质": {"score": 3},
    "职业匹配度": {"score": 2},
    "成长潜力": {"score": 4},
    "基础资质条件": {"score": 3},
}


@pytest.fixture(scope="module", autouse=True)
def clean_jobdims_rows():
    async def _cleanup() -> None:
        async with test_session_factory() as session:
            await session.execute(
                text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
            )
            await session.execute(
                text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
            )
            await session.commit()

    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


class TestExtractJobDimensions:
    def test_standard_shape(self):
        assert extract_job_dimensions(_PORTRAIT) == {
            "专业技术能力": 5.0,
            "实践经验背景": 4.0,
            "通用软素质": 3.0,
            "职业匹配度": 2.0,
            "成长潜力": 4.0,
            "基础资质条件": 3.0,
        }

    def test_flat_and_string_scores(self):
        raw = {"专业技术能力": 4, "实践经验背景": "3"}
        assert extract_job_dimensions(raw) == {"专业技术能力": 4.0, "实践经验背景": 3.0}

    def test_missing_dimensions_are_not_zero_filled(self):
        """**缺的维度不补 0**：不返回 = 没有可比数据。

        补 0 会让学生在 `min(学生分/岗位分)` 里被判成"完全不匹配"（0/岗位分），
        那是**编出来的差距**，比"这一维没有可比数据"更误导。
        """
        out = extract_job_dimensions({"专业技术能力": {"score": 5}})
        assert out == {"专业技术能力": 5.0}
        assert "成长潜力" not in out

    def test_legacy_english_five_dims_are_ignored_on_purpose(self):
        """★ 旧口径的英文五维**不映射**（用户否掉了那个方案）。"""
        legacy = {
            "technical": {"score": 5},
            "experience": {"score": 4},
            "soft_skills": {"score": 3},
            "education": {"score": 2},
            "responsibility": {"score": 1},
        }
        assert extract_job_dimensions(legacy) == {}

    def test_unknown_chinese_keys_are_ignored(self):
        assert extract_job_dimensions({"莫须有维度": {"score": 5}}) == {}

    @pytest.mark.parametrize(
        "raw", [None, "朝阳", 5, [], {"专业技术能力": None}, {"专业技术能力": "高"}]
    )
    def test_bad_shapes_do_not_raise(self, raw):
        assert extract_job_dimensions(raw) == {}

    def test_only_canonical_dims_can_appear(self):
        """返回的键必须是规范六维的子集（防止有人往画像里加私货维度混进匹配）。"""
        out = extract_job_dimensions({**{d: 4 for d in DIMENSION_ORDER}, "私货": 5})
        assert set(out) <= set(DIMENSION_ORDER)
        assert len(out) == len(DIMENSION_ORDER)


class TestJobDimensionScoresReadsPortrait:
    def test_reads_six_dims_from_the_portrait(self):
        async def _seed() -> int:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session,
                    {
                        "title": f"{_PREFIX}_有画像",
                        "company": f"{_PREFIX}_公司甲",
                        "six_dimensions": _PORTRAIT,
                    },
                )
                await session.commit()
                return int(profile.id)

        job_id = asyncio.run(_seed())

        async def _read() -> dict[str, float]:
            async with test_session_factory() as session:
                return await job_dimension_scores(session, job_id)

        assert asyncio.run(_read()) == extract_job_dimensions(_PORTRAIT)

    def test_old_english_portrait_yields_nothing_not_fabricated_scores(self):
        """旧画像（英文五维）→ 返回 `{}`：**如实说不可比**，不翻译、不编。"""
        async def _seed() -> int:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session,
                    {
                        "title": f"{_PREFIX}_旧画像",
                        "company": f"{_PREFIX}_公司乙",
                        "six_dimensions": {"technical": {"score": 5}, "experience": {"score": 4}},
                    },
                )
                await session.commit()
                return int(profile.id)

        job_id = asyncio.run(_seed())

        async def _read() -> dict[str, float]:
            async with test_session_factory() as session:
                return await job_dimension_scores(session, job_id)

        assert asyncio.run(_read()) == {}

    def test_unknown_job_returns_empty(self):
        async def _read() -> dict[str, float]:
            async with test_session_factory() as session:
                return await job_dimension_scores(session, 999999999)

        assert asyncio.run(_read()) == {}
