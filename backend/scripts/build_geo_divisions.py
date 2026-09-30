#!/usr/bin/env python
"""生成 `app/core/geo_divisions.py`：**省 → 市（地级）两级**行政区划参考数据（短名口径）。

为什么需要它
------------
管理端的「省 → 市」级联筛选原先只列**库里出现过的** distinct 值 → 空库（`companies`=0、
`job_company_links`=0）时下拉完全没有选项。用户 2026-09-27 要求**参考民政部行政区划**
（<http://xzqh.mca.gov.cn>）的写法，把标准省市列出来，**只做到省市两级**（不收录区/县）。

数据来源
--------
`modood/Administrative-divisions-of-China` 的 `dist/pc.json`（省级 → 地级），
其数据源自**国家统计局「统计用区划代码」**，写法与民政部 xzqh 平台一致。
> 民政部站点本身是 JS 驱动的查询页，没有可离线取用的结构化接口，故用同一套官方口径的数据集。

本脚本做的三件事（**都是显式变换，不猜**）
------------------------------------------
1. **直辖市**（北京/天津/上海/重庆）：官方第二级是「市辖区」（东城区…）。
   用户裁决：**直辖市第二级 = 它自己**（省=北京、市=北京），因为需求是"只做到省市"，
   列到"区"与之相悖；
2. **补港澳台**（数据集不含，手工补）：台湾省只收**市级**单位（避免"新竹市/新竹县"在短名
   口径下撞成同一个"新竹"），香港/澳门用其惯用分区；
3. 其余保持数据集的官方全名 —— **短名由 `geo_divisions._shorten()` 在导入时推导**
   （规则可读、可测），所以本脚本产出的是**官方全名**，仓库里能直接审计。

用法（需要外网；产物要一起提交）
--------------------------------
    python backend/scripts/build_geo_divisions.py            # 写文件
    python backend/scripts/build_geo_divisions.py --check     # 只比对，不写（CI/复核用）
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/modood/"
    "Administrative-divisions-of-China/master/dist/pc.json"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]
TARGET = BACKEND_DIR / "app" / "core" / "geo_divisions.py"

#: 直辖市：第二级 = 自身（用户 2026-09-27 裁决）
MUNICIPALITIES = ("北京市", "天津市", "上海市", "重庆市")

#: 数据集不含港澳台，手工补（用户要求含港澳台）。
#: 台湾只收市级单位 —— 短名口径下「新竹市」与「新竹县」会撞成同一个「新竹」，
#: 收全反而产生重复项；且需求是"只做到市"。
EXTRA_PROVINCES: dict[str, tuple[str, ...]] = {
    "台湾省": (
        "台北市", "新北市", "桃园市", "台中市", "台南市", "高雄市",
        "基隆市", "新竹市", "嘉义市",
    ),
    "香港特别行政区": ("香港岛", "九龙", "新界"),
    "澳门特别行政区": ("澳门半岛", "氹仔", "路环"),
}

# 注：省级短名的**写死表**在下面 `_FOOTER` 里（它是产物模块的一部分，必须跟着产物走）；
# 本脚本自己不推导短名，只做「直辖市第二级=自身」与「补港澳台」两处变换。

_HEADER = '''"""全国**省 → 市（地级）两级**行政区划参考数据（**本文件由脚本生成，别手改**）。

生成脚本：`backend/scripts/build_geo_divisions.py`（改动请改那边再重跑）。
数据来源：国家统计局「统计用区划代码」口径的 `pc.json`，写法与民政部行政区划平台
（<http://xzqh.mca.gov.cn>）一致。**只到省市两级**，不收录区/县。

两处刻意的加工（见生成脚本 docstring）：
1. 直辖市（北京/天津/上海/重庆）第二级 = **它自己**（省=北京、市=北京）；
2. 手工补了台湾/香港/澳门（数据集不含）。

存的是**官方全名**（`广东省`/`湘西土家族苗族自治州`），
短名（`广东`/`湘西`）由下面的 `_shorten()` 在导入时推导 —— 规则可读可测，
且 `normalise_geo_name()` 靠它与库里已有的写法对上。
"""

from __future__ import annotations

#: 官方全名：省级 → 该省的第二级（地级市 / 地区 / 盟 / 自治州 / 省直辖县级…）
OFFICIAL_PROVINCE_CITIES: dict[str, tuple[str, ...]] = {
'''

_FOOTER = '''

# ── 短名推导（写库与下拉共用同一套规则）──────────────────────────────────────────
# 用户 2026-09-27 裁决：下拉与写库统一用**短名**（广东 / 深圳 / 内蒙古 / 广西 / 湘西 /
# 大兴安岭），与计划 §22.1「存规范化名称（不带省/市后缀）」一致。
#
# 顺序有讲究：先长后缀、再民族名（且**反复剥离**直到不再变化），最后才是省/市/县/区。
# 民族名同时收录「带族」与「不带族」两种写法：自治区去掉「自治区」后剩下的是
# 「广西壮族」「新疆维吾尔」（不带"族"），自治州去掉「自治州」后是「延边朝鲜族」（带"族"）。

#: **省级短名一律写死**（实测踩到：`内蒙古自治区` 剥掉「蒙古」会得到 `内`）。
#: 省级只有 34 个、是封闭集合，写死比"聪明规则"可靠；市/州一级仍走下面的规则推导。
_PROVINCE_OVERRIDES: dict[str, str] = {
    "内蒙古自治区": "内蒙古",
    "广西壮族自治区": "广西",
    "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "香港特别行政区": "香港",
    "澳门特别行政区": "澳门",
}

_ETHNIC_TOKENS: tuple[str, ...] = tuple(
    sorted(
        {
            "土家族", "苗族", "侗族", "藏族", "羌族", "彝族", "白族", "傣族", "景颇族",
            "傈僳族", "哈尼族", "壮族", "布依族", "回族", "蒙古族", "朝鲜族", "哈萨克族",
            "柯尔克孜族", "瑶族", "黎族", "佤族", "拉祜族", "水族", "仡佬族", "满族",
            "土族", "达斡尔族", "鄂温克族", "鄂伦春族", "锡伯族", "撒拉族", "保安族",
            "裕固族", "东乡族", "纳西族", "普米族", "阿昌族", "基诺族", "德昂族",
            "独龙族", "怒族", "门巴族", "珞巴族", "毛南族", "京族", "高山族", "畲族",
            "仫佬族", "维吾尔族",
            # 去掉「自治区/自治州」后可能剩下的**不带"族"**的形式
            "壮族", "维吾尔", "蒙古", "哈萨克", "柯尔克孜", "回族", "朝鲜",
        },
        key=len,
        reverse=True,
    )
)

#: 需要整体去除的后缀（「地区」「盟」「林区」等专名）
_AREA_SUFFIXES: tuple[str, ...] = ("地区", "林区", "盟")
#: 普通行政级别后缀
_PLAIN_SUFFIXES: tuple[str, ...] = ("省", "市", "县", "区")


def _shorten(name: str) -> str:
    """官方全名 → 短名（`广东省`→`广东`；`湘西土家族苗族自治州`→`湘西`）。"""
    text = name.strip()

    if text in _PROVINCE_OVERRIDES:  # 省级全部写死，不走下面的推导
        return _PROVINCE_OVERRIDES[text]

    if text.endswith("特别行政区"):
        return text[: -len("特别行政区")]

    if text.endswith("自治区"):
        base = text[: -len("自治区")]
        for token in _ETHNIC_TOKENS:  # 已按长度倒序：先剥长名，避免"维吾尔"被"吾尔"之类截断
            if base.endswith(token):
                return base[: -len(token)]
        return base  # 内蒙古 / 西藏（本身不含民族名）

    if text.endswith("自治州"):
        base = text[: -len("自治州")]
        changed = True
        while changed:  # 多民族叠加（如"土家族苗族"）要反复剥
            changed = False
            for token in _ETHNIC_TOKENS:
                if base.endswith(token):
                    base = base[: -len(token)]
                    changed = True
                    break
        return base

    for suffix in _AREA_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]

    for suffix in _PLAIN_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]

    return text


#: 短名口径的省市表（下拉与写库都用它）
PROVINCE_CITIES: dict[str, tuple[str, ...]] = {
    _shorten(province): tuple(_shorten(city) for city in cities)
    for province, cities in OFFICIAL_PROVINCE_CITIES.items()
}

#: 任何已知写法 → 短名（全名与短名都在内），供 `normalise_geo_name()` 做规范化
GEO_ALIASES: dict[str, str] = {}
for _province, _cities in OFFICIAL_PROVINCE_CITIES.items():
    _short_province = _shorten(_province)
    GEO_ALIASES[_province] = _short_province
    GEO_ALIASES[_short_province] = _short_province
    for _city in _cities:
        _short_city = _shorten(_city)
        GEO_ALIASES[_city] = _short_city
        GEO_ALIASES[_short_city] = _short_city
del _province, _cities, _short_province, _short_city, _city

#: 省级写法 → 省短名（`normalise_geo_name(kind="province")` 用）。
#: 与 `GEO_ALIASES` 分开是因为**省/市必须能分辨**：`吉林` 既是省短名也是市短名（吉林市），
#: 只靠一张合并表无法回答"这个值是省还是市"。
PROVINCE_ALIASES: dict[str, str] = {}
#: 城市写法 → 市短名（`normalise_geo_name(kind="city")` 用）
CITY_ALIASES: dict[str, str] = {}
for _province, _cities in OFFICIAL_PROVINCE_CITIES.items():
    _sp = _shorten(_province)
    PROVINCE_ALIASES[_province] = _sp
    PROVINCE_ALIASES[_sp] = _sp
    for _city in _cities:
        _sc = _shorten(_city)
        CITY_ALIASES[_city] = _sc
        CITY_ALIASES[_sc] = _sc
del _province, _cities, _sp, _city, _sc

#: 市短名集合（"城市短名出现在任意位置"的兜底匹配用）
CITY_SHORT: frozenset[str] = frozenset(
    city for _cities in PROVINCE_CITIES.values() for city in _cities
)

__all__ = [
    "CITY_ALIASES",
    "CITY_SHORT",
    "GEO_ALIASES",
    "OFFICIAL_PROVINCE_CITIES",
    "PROVINCE_ALIASES",
    "PROVINCE_CITIES",
    "_shorten",
]
'''


def fetch_source() -> dict[str, list[str]]:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as resp:  # noqa: S310 - 固定 https 地址
        return json.loads(resp.read().decode("utf-8"))


def build(raw: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    data: dict[str, tuple[str, ...]] = {}
    for province, cities in raw.items():
        if province in MUNICIPALITIES:
            data[province] = (province,)  # 第二级 = 自身（用户裁决）
        else:
            data[province] = tuple(cities)
    data.update(EXTRA_PROVINCES)
    return data


def render(data: dict[str, tuple[str, ...]]) -> str:
    lines = [_HEADER]
    for province, cities in data.items():
        lines.append(f"    {province!r}: (")
        # 每行塞若干个，保持可读
        row: list[str] = []
        for city in cities:
            row.append(f"{city!r},")
            if len(row) == 6:
                lines.append("        " + " ".join(row))
                row = []
        if row:
            lines.append("        " + " ".join(row))
        lines.append("    ),")
    lines.append("}" + _FOOTER)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成省市两级行政区划参考数据模块")
    parser.add_argument("--check", action="store_true", help="只比对产物是否过期，不写文件")
    args = parser.parse_args(argv)

    try:
        raw = fetch_source()
    except Exception as exc:  # noqa: BLE001 - CLI 入口，给出可读信息即可
        print(f"[FAIL] 取数据源失败（需要外网）：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    data = build(raw)
    text = render(data)

    provinces = len(data)
    cities = sum(len(v) for v in data.values())
    print(f"[INFO] 省级 {provinces} 个 / 第二级 {cities} 条")

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current == text:
            print("[OK]  产物与数据源一致")
            return 0
        print("[DIFF] 产物已过期，请重跑本脚本（不加 --check）", file=sys.stderr)
        return 1

    TARGET.write_text(text, encoding="utf-8")
    print(f"[WRITE] {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
