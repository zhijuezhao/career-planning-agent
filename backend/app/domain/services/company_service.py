"""公司实体服务（B2-2 / B2-5 / 任务 4）：按名称幂等 upsert + 岗位↔公司关联 + 岗位数同步。

为什么单独一层：公司既可能来自导入流水线（`persist` 阶段）、也可能来自
`db_writer` 工具调用或管理端手工建岗位，三处必须用**同一套**归一化与 upsert 规则，
否则同一个公司会被拆成多行（"ABC 科技" vs "ABC科技" 之类）。

B2-5 起新增 `job_company_links`（岗位 ↔ 公司 多对多）：
- 「某家公司有多少岗位」= 该公司关联的**不同岗位**数（`count(distinct job_profile_id)`）；
- 「某个岗位有多少家公司在招」= 该岗位关联的**不同公司**数。
两个方向的计数都以关联表为真相来源，`companies.job_count` 只是它的冗余缓存。

任务 4（2026-09-27）起这里还负责**地域归一化**（`normalise_geo_name`）与
**省市两级级联选项**（`aggregate_geo_options`，参考数据 + 库里 distinct 值合并）。
"""

from __future__ import annotations

from collections.abc import Iterable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo_divisions import (
    CITY_ALIASES,
    CITY_SHORT,
    GEO_ALIASES,
    PROVINCE_ALIASES,
    PROVINCE_CITIES,
    _shorten,
)
from app.domain.models.company import Company
from app.domain.models.job_company_link import JobCompanyLink

# 明显不是公司名的占位值（导入表里常见）
_PLACEHOLDERS = {"nan", "none", "null", "-", "--", "未知", "未提供", "保密", "不详"}

#: 地域占位值：清洗阶段对缺失城市会填「未知」之类，**不能**当作真实省/市写进库，
#: 否则"在未知招的岗位"会污染按地域的筛选与统计（老数据的 `city` 就全是「未知」）。
_GEO_PLACEHOLDERS = frozenset({"未知", "不限", "无", "-", "--", "/", "其他", "nan", "none"})


def normalise_company_name(name: str | None) -> str | None:
    """归一化公司名；无意义的值返回 None（宁可 company_id 为空，也不要脏公司行）。"""
    if name is None:
        return None
    text = " ".join(str(name).split()).strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    return text[:200]


#: `normalise_geo_name(kind=...)` 的两种口径（省 / 市）
GEO_KIND_PROVINCE = "province"
GEO_KIND_CITY = "city"
_GEO_KINDS = frozenset({GEO_KIND_PROVINCE, GEO_KIND_CITY})

#: 前缀匹配的候选，**长名优先** —— 否则 `杭州市` 会被 `杭州` 抢先命中
#: （结果相同，但长名优先对 `吉林市` 这类"省短名也是市短名"的值更稳）。
_PROVINCE_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    sorted(PROVINCE_ALIASES.items(), key=lambda kv: (-len(kv[0]), kv[0]))
)
_CITY_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    sorted(CITY_ALIASES.items(), key=lambda kv: (-len(kv[0]), kv[0]))
)

#: 直辖市：省短名就是它自己的第二级（`北京` 省 → `北京` 市）。
#: 所以 `北京市朝阳区` 剥掉省前缀后剩 `朝阳区`，在**本省候选里**找不到市前缀时，
#: 应当回落到直辖市自身 —— 而**不是**去全表里撞 `朝阳`（辽宁朝阳市）。
_MUNICIPALITY_SHORT = frozenset(
    short for short, cities in PROVINCE_CITIES.items() if short in cities
)


def _leading_province(text: str) -> tuple[str, str] | None:
    """`text` 以某个省级写法开头、且后面还有内容 → 返回 `(匹配到的写法, 省短名)`。"""
    for key, short in _PROVINCE_PREFIXES:
        if text.startswith(key) and len(text) > len(key):
            return key, short
    return None


def _leading_city(text: str, pool: tuple[str, ...] | None = None) -> str | None:
    """`text` 开头命中的**最长**城市短名。

    `pool` 给定时只在其内找（用于"省已确定"的场合，能挡掉别省同名城市的误配）。
    """
    if pool is not None:
        best = ""
        for short in pool:
            if text.startswith(short) and len(short) > len(best):
                best = short
        return best or None
    for key, short in _CITY_PREFIXES:
        if text.startswith(key):
            return short
    return None


def _contained_city(text: str) -> str | None:
    """兜底：城市短名出现在 `text` 的**任意位置**（`中国广东省深圳市` → `深圳`）。

    只在"前缀完全不中"之后才用 —— 它比前缀弱，但**远好过**剥后缀得到的、
    永远筛不到的残值。
    """
    best = ""
    for short in CITY_SHORT:
        if short in text and len(short) > len(best):
            best = short
    return best or None


def _contained_province(text: str) -> str | None:
    """兜底：省级写法出现在 `text` 的**任意位置**（`中国广东省深圳市` → `广东`）。"""
    best = ""
    best_short = ""
    for key, short in _PROVINCE_PREFIXES:
        if key in text and len(key) > len(best):
            best, best_short = key, short
    return best_short or None


def normalise_geo_name(value: object, *, kind: str | None = None) -> str | None:
    """省/市名归一化为**短名**；无意义的值返回 None。

    四步（顺序即优先级）：

    1. 空白 / 占位值（`未知`、`不限`、`-`…）→ `None`。清洗阶段给缺失城市填的「未知」
       **不能**当真实地域入库，否则"在未知招的岗位"会污染按地域的筛选与统计；
    2. **命中参考表** → 用表里的短名。参考表同时收录官方全名与短名，
       所以 `广东省`、`广东` 都会变成 `广东`；
    3. `kind` 给定时的**按级别收敛**（见下）；
    4. 未命中 → 按行政后缀剥一层（`_shorten`），仍为空则 `None`。

    ⚠️ 写库与**下拉选项**共用这一套规则（用户 2026-09-27 裁决"统一短名"）：
    否则导入写进来的是 `广东省`、下拉给出的是 `广东`，筛选就永远对不上。

    ## `kind`：为什么省和市必须分开问（2026-09-29 用户裁决）

    **不传 `kind` = 与 2026-09-27 的行为逐字一致**（零破坏）。传了就按级别收敛：

    | 输入 | `kind=None`（老行为） | `kind="city"` | `kind="province"` |
    |---|---|---|---|
    | `杭州市余杭区` | `杭州市余杭` ❌ | `杭州` | `杭州市余杭` |
    | `深圳市南山区` | `深圳市南山` ❌ | `深圳` | `深圳市南山` |
    | `广东省深圳市` | `广东省深圳` ❌ | `深圳` | `广东` |
    | `广东省深圳市南山区` | `广东省深圳市南山` ❌ | `深圳` | `广东` |
    | `内蒙古自治区呼和浩特市新城区` | `…市新城` ❌ | `呼和浩特` | `内蒙古` |
    | `北京市朝阳区` | `北京市朝阳` ❌ | `北京` | `北京` |

    老行为的问题：只剥**最后**一个后缀，得到的 `杭州市余杭` 既不是市也不是区，
    **按市筛选永远匹配不上**（B3-2 报告 → §31.11 ①）。

    **为什么要两个口径而不是一个更聪明的函数**：`city` 列可能是链式写法
    `广东省深圳市`，同一个值在 `region` 列的正确答案是 `广东` ——
    **字段无关的函数无法同时给出这两个答案**。

    ⚠️ **已知歧义（不猜）**：**裸区名**（只有 `朝阳区`、不带市/省）无法判断属于哪个市，
    会命中最长城市前缀 `朝阳`（辽宁朝阳市），而它多半是北京朝阳区。
    参考数据**只做到省市两级**（用户 2026-09-27 要求），三级数据不在表内 ——
    这里不做猜测，也不为此引入第三级数据。
    """
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    if not text or text.lower() in _GEO_PLACEHOLDERS:
        return None

    if kind is not None and kind not in _GEO_KINDS:
        raise ValueError(f"未知的 kind：{kind!r}（只接受 None / 'province' / 'city'）")

    canonical = GEO_ALIASES.get(text)
    if canonical:
        if kind is None:
            return canonical
        # 分口径：要判断**输入本身**是不是该级别的写法，而不是"短名恰好也在该级别里"。
        # 反例（2026-09-29 实测）：`海南藏族自治州`（青海）的短名是 `海南`，而
        # `海南` 同时是省短名 —— 用"短名在省集合里"判就会把它当成海南省。
        if kind == GEO_KIND_PROVINCE and text in PROVINCE_ALIASES:
            return PROVINCE_ALIASES[text]
        if kind == GEO_KIND_CITY and text in CITY_ALIASES:
            return CITY_ALIASES[text]

    if kind == GEO_KIND_CITY:
        lead = _leading_province(text)
        if lead:
            key, province = lead
            rest = text[len(key) :]
            # 省已确定 → **只在该省的城市里**找，避免撞到别省的同名/近名城市
            city = _leading_city(rest, PROVINCE_CITIES.get(province, ()))
            if city:
                return city
            if province in _MUNICIPALITY_SHORT:
                # 直辖市：第二级就是它自己（`北京市朝阳区` → `北京`）
                return province
        else:
            city = _leading_city(text)
            if city:
                return city

        contained = _contained_city(text)
        if contained:
            return contained
        return _shorten(text).strip() or None

    if kind == GEO_KIND_PROVINCE:
        # ⚠️ 保护：**本身就是一个已知城市写法**的值，绝不去剥它的省级前缀。
        # 反例（2026-09-29 实测）：`海南藏族自治州`（青海）以省写法 `海南` 开头，
        # 不设这道保护就会被判成海南省；`吉林市` 同理（虽结果相同）。
        # 命中保护时退回**与不传 kind 完全相同**的行为，不做猜测。
        if text in CITY_ALIASES and text not in PROVINCE_ALIASES:
            return _shorten(text).strip() or None
        lead = _leading_province(text)
        if lead:
            return lead[1]
        contained = _contained_province(text)
        if contained:
            return contained
        return _shorten(text).strip() or None

    shortened = _shorten(text).strip()
    return shortened or None


#: 城市短名 → 省份短名（由 `PROVINCE_CITIES` 反向构建，**纯派生**，无人工数据）
_CITY_TO_PROVINCE: dict[str, str] = {
    city: province for province, cities in PROVINCE_CITIES.items() for city in cities
}


def province_of_city(city: object) -> str | None:
    """由**城市**反查省份短名；查不到返回 ``None``。

    存在的原因（2026-10-03）：用户的导入表**没有「省份」列**（实测 524 行表 12 列里没有），
    于是 `companies.region` 全是 `None` —— 管理端「先选省、再选市」的**省份列表会是空的**。
    实测这份表的 70 个城市 **70/70** 都能在本表里查到省份，所以推导是可靠的、零成本的。

    先走 `normalise_geo_name(kind='city')` 取短名，保证与写库/下拉同一套写法。
    """
    if city is None:
        return None
    short = normalise_geo_name(city, kind=GEO_KIND_CITY)
    if not short:
        return None
    return _CITY_TO_PROVINCE.get(short)


async def upsert_company(
    session: AsyncSession,
    name: str | None,
    *,
    industry: str | None = None,
    city: str | None = None,
    region: str | None = None,
    scale: str | None = None,
) -> Company | None:
    """按 name 取公司，没有则建。

    industry / city / region / scale **只在公司行为空时补全**：这些字段允许管理端手工修正，
    后续导入不应把它们覆盖回去。

    地域（region/city）在这里统一走 `normalise_geo_name()` → **短名入库**，
    保证与下拉选项同一套写法（任务 4）。
    """
    clean = normalise_company_name(name)
    if clean is None:
        return None

    region = normalise_geo_name(region, kind=GEO_KIND_PROVINCE)
    city = normalise_geo_name(city, kind=GEO_KIND_CITY)

    company = (
        await session.execute(select(Company).where(Company.name == clean).limit(1))
    ).scalar_one_or_none()

    if company is None:
        company = Company(
            name=clean,
            industry=(industry or None),
            city=city,
            region=region,
            scale=(scale or None),
            job_count=0,
        )
        session.add(company)
        await session.flush()
        logger.info("公司表新增 | id={} | name={!r}", company.id, clean)
        return company

    for field, value in (
        ("industry", industry),
        ("city", city),
        ("region", region),
        ("scale", scale),
    ):
        if value and not getattr(company, field):
            setattr(company, field, value)
    return company


async def link_job_company(
    session: AsyncSession,
    *,
    job_profile_id: int,
    company_id: int,
    source: str = "import",
    region: str | None = None,
    city: str | None = None,
    salary: str | None = None,
    source_url: str | None = None,
) -> JobCompanyLink:
    """建立/更新「岗位 ↔ 公司」关联（幂等；重复出现时累加 hit_count）。

    这张表是「**谁在招谁**」的**唯一真相**（岗位↔公司 多对多）。每条关联 = **一次招聘**，
    所以招聘所在地（省/市）、薪资、原始链接挂在这里 —— 同一个岗位角色在不同公司在招时，
    这三项必然不同。

    取值策略：**非空的新值覆盖旧值**（表格是这次招聘的事实来源），空值不覆盖。
    地域同样归一化为**短名**（与下拉选项同一套写法）。
    """
    region = normalise_geo_name(region, kind=GEO_KIND_PROVINCE)
    city = normalise_geo_name(city, kind=GEO_KIND_CITY)

    link = (
        await session.execute(
            select(JobCompanyLink).where(
                JobCompanyLink.job_profile_id == job_profile_id,
                JobCompanyLink.company_id == company_id,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        link = JobCompanyLink(
            job_profile_id=job_profile_id,
            company_id=company_id,
            source=source,
            hit_count=1,
            region=region,
            city=city,
            salary=(salary or None),
            source_url=(source_url or None),
        )
        session.add(link)
        await session.flush()
        logger.info(
            "岗位↔公司关联新增 | job_profile_id={} | company_id={}", job_profile_id, company_id
        )
        return link

    for field, value in (
        ("region", region),
        ("city", city),
        ("salary", salary),
        ("source_url", source_url),
    ):
        if value:
            setattr(link, field, value)
    link.hit_count += 1
    link.last_seen_at = func.now()
    return link


async def company_job_count(session: AsyncSession, company_id: int) -> int:
    """该公司在招的不同岗位数（以关联表为准）。"""
    return (
        await session.execute(
            select(func.count(func.distinct(JobCompanyLink.job_profile_id))).where(
                JobCompanyLink.company_id == company_id
            )
        )
    ).scalar() or 0


async def refresh_job_count(session: AsyncSession, company_id: int) -> int:
    """按关联表重算并回写 `companies.job_count`（冗余列的真相来源）。"""
    count = await company_job_count(session, company_id)
    company = await session.get(Company, company_id)
    if company is not None and company.job_count != count:
        company.job_count = count
    return count


async def sync_all_job_counts(session: AsyncSession) -> int:
    """全量重算所有公司的 job_count（修数 / 人工改过关联后用）。"""
    companies = list((await session.execute(select(Company))).scalars().all())
    for company in companies:
        await refresh_job_count(session, company.id)
    return len(companies)


def aggregate_geo_options(
    pairs: Iterable[tuple[str | None, str | None]], *, include_reference: bool = True
) -> dict[str, object]:
    """把 `(省, 市)` 明细汇总成**省 → 市 级联下拉**要的三份数据（纯函数，无 IO）。

    返回 `{"regions": [...], "cities_by_region": {省: [市...]}, "all_cities": [...]}`，
    三份都是**排序去重**的（排序即前端下拉的稳定顺序，省得前端再排一遍）。

    - `regions`：有省的 distinct 省；
    - `cities_by_region`：省 → 该省的市；
    - `all_cities`：全部市 —— 含"只写了市、没写省"的行，否则这些行在当前筛选器里
      **永远筛不到**（选中它们的省是做不到的，因为压根没有省）。

    `include_reference=True`（默认）时，结果 = **官方行政区划参考数据**（省→市两级，
    见 `app/core/geo_divisions.py`）**∪ 库里出现的值**：

    - 参考数据让下拉在**空库**时也有标准省市可选（用户 2026-09-27 要求参考民政部写法）；
    - 合并库里的值是为了**不丢**导入来的非标准写法 —— 否则那些行筛得到却选不到，
      或者选得到却筛不到。

    放在服务层但**不 import schemas**：返回普通 dict，由接口侧包成 `GeoOptionsResponse`，
    免得领域层反向依赖接口契约。
    """
    regions: set[str] = set()
    cities_by_region: dict[str, set[str]] = {}
    all_cities: set[str] = set()

    if include_reference:
        for province, cities in PROVINCE_CITIES.items():
            regions.add(province)
            cities_by_region.setdefault(province, set()).update(cities)
            all_cities.update(cities)

    for raw_region, raw_city in pairs:
        region = str(raw_region).strip() if raw_region is not None else ""
        city = str(raw_city).strip() if raw_city is not None else ""
        if region:
            regions.add(region)
        if city:
            all_cities.add(city)
            if region:
                cities_by_region.setdefault(region, set()).add(city)

    return {
        "regions": sorted(regions),
        "cities_by_region": {
            region: sorted(cities) for region, cities in sorted(cities_by_region.items())
        },
        "all_cities": sorted(all_cities),
    }


__all__ = [
    "GEO_KIND_CITY",
    "GEO_KIND_PROVINCE",
    "aggregate_geo_options",
    "company_job_count",
    "link_job_company",
    "normalise_company_name",
    "normalise_geo_name",
    "province_of_city",
    "refresh_job_count",
    "sync_all_job_counts",
    "upsert_company",
]
