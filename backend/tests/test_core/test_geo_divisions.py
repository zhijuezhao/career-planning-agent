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


class TestKindAwareNormalisation:
    """§31.11 ①（2026-09-29 用户裁决）：省/市**分口径**收敛。

    老行为只剥**最后一个**行政后缀 → `杭州市余杭区` → `杭州市余杭`，
    得到的值既不是市也不是区，**按市筛选永远匹配不上**（B3-2 报告 → §31.11 ①）。

    **不传 `kind` 的默认口径与老行为逐字一致**（上面 `TestNormaliseGeoName` 钉住），
    所以这次改动对既有调用方零破坏。
    """

    @pytest.mark.parametrize(
        ("raw", "expect_city", "expect_province"),
        [
            # 区级：链接里最常见的形态 → 收敛到它所属的市
            ("杭州市余杭区", "杭州", "杭州市余杭"),
            ("深圳市南山区", "深圳", "深圳市南山"),
            ("苏州工业园区", "苏州", "苏州工业园"),
            # 直辖市：第二级就是自身（用户 2026-09-27 裁决"只做到省市"）
            ("北京市海淀区", "北京", "北京"),
            ("上海市浦东新区", "上海", "上海"),
            ("北京市朝阳区", "北京", "北京"),
            ("重庆市万州区", "重庆", "重庆"),
            # 链式「省+市」：**这就是必须分口径的原因** ——
            # 同一个值在 city 列要 `深圳`、在 region 列要 `广东`，一个字段无关的
            # 函数给不出两个答案。
            ("广东省深圳市", "深圳", "广东"),
            ("广东省深圳市南山区", "深圳", "广东"),
            ("浙江杭州余杭区", "杭州", "浙江"),
            ("内蒙古自治区呼和浩特市新城区", "呼和浩特", "内蒙古"),
            ("中国广东省深圳市", "深圳", "广东"),
            # 干净值不受影响
            ("杭州市", "杭州", "杭州"),
            ("广东省", "广东", "广东"),
            ("深圳", "深圳", "深圳"),
        ],
    )
    def test_converges_to_the_right_level(self, raw, expect_city, expect_province):
        assert normalise_geo_name(raw, kind="city") == expect_city
        assert normalise_geo_name(raw, kind="province") == expect_province

    def test_known_city_name_starting_with_a_province_is_not_mistaken(self):
        """`海南藏族自治州`（青海）以省写法 `海南` 开头 —— 不能因此判成海南省。

        它的短名恰好**也是** `海南`（与省短名同名），所以判据必须是"**输入本身**
        是不是省级写法"，而不是"短名在不在省集合里"。这里钉住"与不传 kind 的结果
        一致"，即**没有引入新的误判**。
        """
        assert normalise_geo_name("海南藏族自治州", kind="province") == normalise_geo_name(
            "海南藏族自治州"
        )
        assert normalise_geo_name("吉林市", kind="province") == "吉林"  # 省短名=市短名，结果相同

    def test_bare_district_is_not_guessed_from_thin_air(self):
        """裸区名（不带市/省）**不做三级猜测**。

        参考数据只到省市两级（用户 2026-09-27 要求），拿不到"这个区属于哪个市"的
        依据 —— 所以只能退化成"剥后缀"，而**不能**凭空编一个市出来。
        `朝阳区` 命中最长城市前缀会得到辽宁的 `朝阳`，这是已知歧义（见 docstring）。
        """
        assert normalise_geo_name("朝阳区", kind="city") == "朝阳"

    def test_placeholders_still_none_in_both_kinds(self):
        for raw in (None, "", "   ", "未知", "不限", "-", "--", "/"):
            assert normalise_geo_name(raw, kind="city") is None
            assert normalise_geo_name(raw, kind="province") is None

    def test_unknown_kind_is_rejected_loudly(self):
        """`kind` 写错要**立刻报错**，不能静默退回默认口径（否则口径错误无从发现）。"""
        with pytest.raises(ValueError, match="kind"):
            normalise_geo_name("广东", kind="district")
