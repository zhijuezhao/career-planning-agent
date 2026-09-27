"""`radar_option`（P5 六维雷达）的测试 —— 纯函数，钉住形状与两条硬约束。

两条硬约束（都会被前端直接看到，所以必须有测试）：
1. **轴顺序**：轴必须按调用方给的顺序（= `DIMENSION_ORDER`），否则两次对比的轴会错位，
   雷达图看起来"变了形"，人却一眼看不出原因；
2. **缺维不许用 0 顶替**：0 会被读成"这一维极差"，而事实是"没有可比数据"
   —— 与 P5 的"不编数据"原则一致（`job_dimension_scores` 缺维就不返回）。
"""

from __future__ import annotations

import pytest
from app.core.chat.viz import (
    RADAR_COLORS,
    RADAR_MAX,
    echarts_viz,
    is_valid_viz,
    radar_option,
)
from app.core.dimensions.rubrics import DIMENSION_ORDER


class TestRadarOption:
    def test_axes_follow_the_given_dimension_order(self):
        dims = list(DIMENSION_ORDER)
        option = radar_option(dims, {"我": [1, 2, 3, 4, 5, 1]})
        assert [i["name"] for i in option["radar"]["indicator"]] == dims
        assert all(i["max"] == RADAR_MAX for i in option["radar"]["indicator"])

    def test_six_dimensions_by_default_rubric_order(self):
        option = radar_option(list(DIMENSION_ORDER), {"岗位": [3] * 6})
        assert len(option["radar"]["indicator"]) == 6
        assert option["series"][0]["type"] == "radar"

    def test_multi_series_keeps_order_and_assigns_distinct_colors(self):
        option = radar_option(list(DIMENSION_ORDER), {"我": [4] * 6, "岗位": [3] * 6})
        data = option["series"][0]["data"]
        assert [d["name"] for d in data] == ["我", "岗位"]
        assert data[0]["itemStyle"]["color"] != data[1]["itemStyle"]["color"]
        assert option["legend"]["data"] == ["我", "岗位"]

    def test_missing_dimension_may_be_none(self):
        """缺维传 `None`（ECharts 会断开），**不是** 0。"""
        option = radar_option(list(DIMENSION_ORDER), {"岗位": [3, None, 3, None, 3, 3]})
        assert option["series"][0]["data"][0]["value"][1] is None

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="不一致"):
            radar_option(list(DIMENSION_ORDER), {"我": [1, 2]})

    def test_empty_dimensions_raises(self):
        with pytest.raises(ValueError, match="至少一个维度"):
            radar_option([], {})

    def test_wraps_into_a_valid_viz(self):
        """必须能通过 `is_valid_viz`（否则落库/下发前会被丢掉）。"""
        viz = echarts_viz("radar", "六维对比", radar_option(list(DIMENSION_ORDER), {"我": [4] * 6}))
        assert is_valid_viz(viz)
        assert viz["kind"] == "radar"

    def test_colors_are_stable(self):
        """配色表是给前端用的契约，别悄悄改（改了就前后端不一致）。"""
        assert RADAR_COLORS[0] == "#409eff"
        assert isinstance(RADAR_COLORS, tuple)
