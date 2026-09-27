"""行政区划参考数据 + 地域归一化（任务 4 续，2026-09-27）。

用户要求：**参考民政部行政区划**（<http://xzqh.mca.gov.cn>）的写法，管理端「先选省、再选市」，
**只做到省市两级**；下拉与写库统一用**短名**（广东 / 深圳 / 内蒙古 / 湘西）。

本文件是**纯函数/纯数据**测试（不碰库）：
1. 参考数据自身的体检（省级数、无空/无省内重复、直辖市、港澳台、短名写死表）；
2. `normalise_geo_name()` 的映射规则（含把「广东省」收敛成「广东」这种跨写法归一）。

数据由 `backend/scripts/build_geo_divisions.py` 生成，源是国家统计局「统计用区划代码」
口径的数据集；本文件把其中**容易出错的那几个**钉成断言。
"""

from __future__ import annotations

import pytest
from app.core.geo_divisions import (
    GEO_ALIASES,
    OFFICIAL_PROVINCE_CITIES,
    PROVINCE_CITIES,
    _shorten,
)
from app.domain.services.company_service import normalise_geo_name

#: 直辖市：第二级 = 自身（用户 2026-09-27 裁决：只做到省市，不列"区"）
MUNICIPALITIES = ("北京", "天津", "上海", "重庆")


class TestReferenceData:
    def test_covers_34_provinces_including_hk_mo_tw(self):
        assert len(PROVINCE_CITIES) == 34
        assert {"台湾", "香港", "澳门"} <= set(PROVINCE_CITIES)

    def test_two_levels_only_no_empty_or_duplicate(self):
        """结构上**只有两级**，且每个省的市列表非空、省内不重复。"""
        for province, cities in PROVINCE_CITIES.items():
            assert cities, f"{province} 的第二级为空"
            assert len(set(cities)) == len(cities), f"{province} 省内出现重复的市：{cities}"
            for city in cities:
                assert isinstance(city, str) and city.strip(), f"{province} 有空的市级名"
                # 第二级不该再有"省"（那说明层级串了）
                assert not city.endswith("省"), f"{province} 的第二级混进了省：{city}"

    def test_municipalities_second_level_is_itself(self):
        for name in MUNICIPALITIES:
            assert PROVINCE_CITIES[name] == (name,), f"{name} 的第二级应当是它自己"

    @pytest.mark.parametrize(
        ("official", "expected"),
        [
            # ⚠️ 回归：规则版曾把「内蒙古自治区」剥成 **「内」**（民族名「蒙古」吃掉了专名）
            # → 所以省级短名改成写死表，这条钉住它
            ("内蒙古自治区", "内蒙古"),
            ("广西壮族自治区", "广西"),
            ("新疆维吾尔自治区", "新疆"),
            ("宁夏回族自治区", "宁夏"),
            ("西藏自治区", "西藏"),
            ("香港特别行政区", "香港"),
            ("澳门特别行政区", "澳门"),
            ("北京市", "北京"),
            ("黑龙江省", "黑龙江"),
        ],
    )
    def test_province_short_names_are_fixed(self, official, expected):
        assert official in OFFICIAL_PROVINCE_CITIES, f"{official} 不在参考数据里"
        assert _shorten(official) == expected
        assert expected in PROVINCE_CITIES

    @pytest.mark.parametrize(
        ("official", "expected"),
        [
            ("湘西土家族苗族自治州", "湘西"),
            ("恩施土家族苗族自治州", "恩施"),
            ("海西蒙古族藏族自治州", "海西"),
            ("克孜勒苏柯尔克孜自治州", "克孜勒苏"),
            ("巴音郭楞蒙古自治州", "巴音郭楞"),
            ("伊犁哈萨克自治州", "伊犁"),
            ("黔西南布依族苗族自治州", "黔西南"),
            ("大兴安岭地区", "大兴安岭"),
            ("锡林郭勒盟", "锡林郭勒"),
            ("神农架林区", "神农架"),
        ],
    )
    def test_city_short_names_are_derived_correctly(self, official, expected):
        """市/州一级走规则推导（省级才写死）—— 这几个是最容易剥错的。"""
        assert _shorten(official) == expected

    def test_aliases_map_both_writings_to_short(self):
        assert GEO_ALIASES["广东省"] == "广东"
        assert GEO_ALIASES["广东"] == "广东"
        assert GEO_ALIASES["深圳市"] == "深圳"
        assert GEO_ALIASES["深圳"] == "深圳"


class TestNormaliseGeoName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # 官方全名 → 短名（导入表里两种写法都可能出现）
            ("广东省", "广东"),
            ("深圳市", "深圳"),
            ("内蒙古自治区", "内蒙古"),
            ("广西壮族自治区", "广西"),
            ("新疆维吾尔自治区", "新疆"),
            ("湘西土家族苗族自治州", "湘西"),
            ("大兴安岭地区", "大兴安岭"),
            # 已经是短名 → 原样
            ("广东", "广东"),
            ("深圳", "深圳"),
            ("北京", "北京"),
            ("东莞", "东莞"),
            # 前后空白要吃掉
            ("  广东  ", "广东"),
            # 参考表里没有的值：按行政后缀剥一层后保留（**不丢**导入来的写法）
            ("某个测试市", "某个测试"),
        ],
    )
    def test_maps_to_short_name(self, raw, expected):
        assert normalise_geo_name(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "未知", "不限", "-", "--", "/", "其他", "nan", "None"])
    def test_placeholders_and_blank_become_none(self, raw):
        """占位值**不能**当真实地域入库（否则"在未知招的岗位"污染地域筛选）。"""
        assert normalise_geo_name(raw) is None
