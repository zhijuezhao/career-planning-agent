"""六维评分标准的**两套标准 + 单一来源**测试（P5 口径统一的地基）。

用户 2026-09-27 的原始要求（本文件的断言就是照着它写的）：
> 「两套都走六维，但是**评分标准不要照搬**，一个是学生能力侧，一个是岗位能力侧，
>   **两种做好规划**，而且**方便我进行迭代升级**」以及「两侧同名，具体细节要做好，
>   **不能不考虑就照搬**」。

所以这里钉四件事：
1. **单一来源**：`resume_agent.schemas` 的维度定义就是从 rubric 模块来的（不许各写一份）；
2. **两侧同名**：维度与子维度两侧**完全一致**（否则 `job_matcher` 逐维对比对不上）；
3. **两侧不照搬**：每一维的 `focus` 与 1–5 锚点，两侧**必须不同**（这是"分侧设计"的硬约束）；
4. **可迭代**：改数据即改标准；渲染出来的提示词片段含全部维度/子维/档位，且有版本号。
"""

from __future__ import annotations

import pytest
from app.core.dimensions.rubrics import (
    DIMENSION_ORDER,
    DIMENSIONS,
    LEVEL_MEANING,
    RUBRIC_VERSION,
    RUBRICS,
    render_rubric,
    validate_rubrics,
)
from app.core.resume_agent.schemas import (
    ALL_SUB_DIM_KEYS,
    SUB_DIMENSIONS,
    TOP_DIMENSIONS,
)


class TestSingleSourceOfTruth:
    def test_schemas_reexports_the_rubric_dimensions(self):
        """学生侧 schema 不许自己再写一份维度定义（否则两侧必然漂移）。"""
        assert TOP_DIMENSIONS == list(DIMENSION_ORDER)
        assert SUB_DIMENSIONS == {dim: list(subs) for dim, subs in DIMENSIONS.items()}
        assert set(ALL_SUB_DIM_KEYS) == {
            sub for subs in DIMENSIONS.values() for sub in subs
        }

    def test_validate_accepts_current_data(self):
        validate_rubrics()  # 不抛即通过（导入时也已跑过一次）

    def test_validate_catches_dimension_drift(self, monkeypatch):
        """自检必须真的会炸：漏掉一侧的一个维度要能被抓住。"""
        broken = {side: dict(dims) for side, dims in RUBRICS.items()}
        broken["job"] = {k: v for k, v in broken["job"].items() if k != "成长潜力"}
        monkeypatch.setattr("app.core.dimensions.rubrics.RUBRICS", broken)
        with pytest.raises(RuntimeError, match="维度不匹配"):
            validate_rubrics()


class TestBothSidesSameDimensions:
    def test_both_sides_cover_exactly_the_six_dimensions(self):
        assert set(RUBRICS) == {"candidate", "job"}
        for side in RUBRICS:
            assert set(RUBRICS[side]) == set(DIMENSIONS)

    def test_both_sides_cover_the_same_sub_dimensions(self):
        for side in RUBRICS:
            for dim, subs in DIMENSIONS.items():
                assert set(RUBRICS[side][dim]["sub_dimensions"]) == set(subs), (side, dim)

    @pytest.mark.parametrize("side", ["candidate", "job"])
    def test_anchors_are_complete_and_ordered(self, side):
        for dim, spec in RUBRICS[side].items():
            assert sorted(spec["anchors"]) == [1, 2, 3, 4, 5], (side, dim)
            for level in (1, 2, 3, 4, 5):
                assert spec["anchors"][level].strip(), f"{side}/{dim}/{level} 锚点为空"


class TestRubricsAreNotCopied:
    """★ 用户明确要求：**评分标准不要照搬** —— 逐维钉住"两侧不同"。"""

    @pytest.mark.parametrize("dim", list(DIMENSIONS))
    def test_focus_differs_between_sides(self, dim):
        assert RUBRICS["candidate"][dim]["focus"] != RUBRICS["job"][dim]["focus"], (
            f"{dim} 的「看什么」两侧一模一样 —— 那是照搬，不是分侧设计"
        )

    @pytest.mark.parametrize("dim", list(DIMENSIONS))
    def test_all_five_anchors_differ_between_sides(self, dim):
        cand = RUBRICS["candidate"][dim]["anchors"]
        job = RUBRICS["job"][dim]["anchors"]
        same = [level for level in (1, 2, 3, 4, 5) if cand[level] == job[level]]
        assert not same, f"{dim} 的 {same} 档两侧文字相同 —— 侧重点没分开"

    @pytest.mark.parametrize("dim", list(DIMENSIONS))
    def test_sub_dimension_guidance_differs_between_sides(self, dim):
        cand = RUBRICS["candidate"][dim]["sub_dimensions"]
        job = RUBRICS["job"][dim]["sub_dimensions"]
        same = [sub for sub in cand if cand[sub] == job[sub]]
        assert not same, f"{dim} 的子维度 {same} 两侧指导语相同 —— 细节要分侧写"

    def test_level_ladders_are_side_specific(self):
        """总纲阶梯也必须分侧（一个是"能力水平"，一个是"要求强度"）。"""
        assert LEVEL_MEANING["candidate"] != LEVEL_MEANING["job"]
        assert "无相关证据" in LEVEL_MEANING["candidate"][1]
        assert "几乎无要求" in LEVEL_MEANING["job"][1]


class TestRenderRubric:
    @pytest.mark.parametrize("side", ["candidate", "job"])
    def test_renders_every_dimension_sub_dimension_and_level(self, side):
        text = render_rubric(side)
        for dim in DIMENSION_ORDER:
            assert dim in text, f"{side} 渲染结果缺维度 {dim}"
            for sub in DIMENSIONS[dim]:
                assert sub in text, f"{side} 渲染结果缺子维度 {sub}"
            for level in (1, 2, 3, 4, 5):
                assert f"{level} 分" in text

    def test_two_sides_render_differently(self):
        assert render_rubric("candidate") != render_rubric("job")

    def test_unknown_side_raises(self):
        with pytest.raises(KeyError, match="未知的评分侧"):
            render_rubric("teacher")

    def test_version_is_present_for_traceability(self):
        """入库要记版本 → 形状得稳定（`YYYY-MM-DD.N`）。"""
        assert RUBRIC_VERSION
        head, _, tail = RUBRIC_VERSION.partition(".")
        assert len(head) == 10 and head[4] == "-" and head[7] == "-"
        assert tail.isdigit()
