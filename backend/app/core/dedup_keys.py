"""岗位去重键（P2，2026-09-26 用户拍板；2026-09-27 任务 3 收口；2026-10-03 B4 加等级）。

**粒度分两层，别混**：

- **落库唯一键**（`job_profiles`）= **归一化岗位名 + 等级**（`uq_job_profiles_title_level`）。
  岗位是**角色级**的，"同名被 N 家公司招" = **1 条岗位 + N 条 `job_company_links`**
  （用户 2026-09-27 拍板的多对多），不再像 P2 那样落成 N 条画像。
  B4（2026-10-03）起用户要求「划分出初中高级岗位」，于是唯一键再加一维等级：
  同一个岗位名按 初级/中级/高级/不限 各留一条画像（`level` 必须 NOT NULL，
  否则唯一索引里的 NULL 互不相等会写出重复行）。
- **文件内去重**（`job_dedup_key`）= `(归一化岗位名, 归一化公司名)`。这是"同一份表里
  两行是否重复"的判断：同名**同公司**才是重复；同名**不同公司**必须都留下，
  否则会丢掉一条在招关联。

为什么把归一化单独放一层：
`job_profiles.title_key` 是**数据库生成列**（`lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))`），
落库 upsert 与流水线内的文件去重必须用**同一套规则**，否则会出现
"DB 认为重复、应用查不到 → 插入 → 唯一索引报错"。
这里只放**纯 Python** 实现（无 SQLAlchemy），SQL 侧表达式见 `TITLE_KEY_SQL`
（`job_persist_service`）与 `apply_ddl.py` 的 DDL，三处必须逐字一致。

规则（用户 2026-09-26 选定）：忽略大小写 + 折叠空白。
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")

#: 岗位名的归一化 SQL 表达式（供 DDL 与 ORM 生成列引用，保持单一来源可读）
TITLE_KEY_SQL = "lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))"

#: 占位公司名（导入表里常见的"没有公司"写法）；与 `company_service._PLACEHOLDERS` 同义
_COMPANY_PLACEHOLDERS = frozenset(
    {"nan", "none", "null", "-", "--", "未知", "未提供", "保密", "不详"}
)


def normalise_title(text: object) -> str:
    """岗位名归一化：折叠空白 + 去首尾 + 转小写。空值/`nan` 一律返回空串。

    与 `job_profiles.title_key` 生成列（`lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))`）
    **语义等价** —— Python 侧 `str.split()` 折叠所有空白字符，PG 侧 `\\s+` 同理。
    """
    if text is None:
        return ""
    value = str(text)
    if value.strip().lower() in ("nan", "none"):
        return ""
    return " ".join(value.split()).lower()


def normalise_company_name(name: object) -> str | None:
    """公司名归一化：折叠空白；占位值返回 None（= 没有公司信息）。

    与 `company_service.normalise_company_name` 同规则（那边多一层 200 字截断，
    那是给人看的存储值，这里只用于**比较**）。**刻意不转小写**：公司名的大小写
    属于显示信息，而真正的键用的是 `companies.id`（`name` 本身已有 UNIQUE 约束）。
    """
    if name is None:
        return None
    text = " ".join(str(name).split()).strip()
    if not text or text.lower() in _COMPANY_PLACEHOLDERS:
        return None
    return text


def job_dedup_key(title: object, company: object) -> tuple[str, str]:
    """**文件内**去重用的键：`(归一化岗位名, 归一化公司名或空串)`。

    公司为空串表示"未知公司"。注意这是"同一份表里是否同一行"的判断，**不是**落库唯一键
    ——落库唯一键只有岗位名（见模块 docstring）：同名不同公司要保留成**两条关联**。
    """
    return normalise_title(title), (normalise_company_name(company) or "")


#: URL 的查询串与 fragment（`?refcode=…&preactionid=…` / `#anchor`）
_URL_QUERY_OR_FRAGMENT = re.compile(r"[?#].*$", re.DOTALL)

_URL_PLACEHOLDERS = frozenset({"none", "nan", "null", "-", "--", "无", "未知"})


def normalise_source_url(url: object) -> str | None:
    """岗位来源链接归一化：**去掉查询串与 fragment**；占位值返回 None。

    为什么必须去查询串（2026-10-03 实测用户真实数据）：
    智联的岗位详情 URL 形如::

        https://www.zhaopin.com/jobdetail/CC383625320J40658720509.htm
            ?refcode=4019&srccode=401901&preactionid=<导出会话id>

    其中 `preactionid` 在**一次导出里只有一个值**（我实测 524 行全表就 1 个值）——
    它是**导出会话 id**，用户下次重新导出同一批岗位时它一定会变。
    若拿完整 URL 当去重键 / 幂等键，"同一份表再导一次"会被判成一批全新岗位，
    幂等性直接失效。去掉查询串后剩下的路径段（`…/CC…htm`）里嵌的就是岗位编码，稳定。
    """
    if url is None:
        return None
    text = " ".join(str(url).split()).strip()
    if not text or text.lower() in _URL_PLACEHOLDERS:
        return None
    return _URL_QUERY_OR_FRAGMENT.sub("", text) or None


__all__ = [
    "TITLE_KEY_SQL",
    "job_dedup_key",
    "normalise_company_name",
    "normalise_source_url",
    "normalise_title",
]
