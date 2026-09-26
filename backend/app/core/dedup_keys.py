"""岗位去重键（P2，2026-09-26 用户拍板）。

**粒度**：`(归一化岗位名, 公司)`。同一岗位名 × N 家公司 = **N 条画像**；
没有公司数据时退化为「按岗位名唯一」（`company_id IS NULL` 视为同一个"未知公司桶"）。

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
    """文件内去重用的键：`(归一化岗位名, 归一化公司名或空串)`。

    公司为空串表示"未知公司"——与落库层 `company_id IS NULL` 的"未知公司桶"对应。
    """
    return normalise_title(title), (normalise_company_name(company) or "")


__all__ = [
    "TITLE_KEY_SQL",
    "job_dedup_key",
    "normalise_company_name",
    "normalise_title",
]
