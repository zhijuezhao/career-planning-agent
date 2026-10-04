#!/usr/bin/env python
"""幂等应用批 2 / 批 3 的全部 DDL（方案 A：不依赖 alembic 基线）。

背景（为什么需要这个脚本）：
    * 开发库**没有 `alembic_version` 表**（迁移从未落库），直接 `alembic upgrade head`
      会尝试从零建表并与既有 17 张表冲突；
    * `Base.metadata.create_all()` **不会给既有表加列**（它不 ALTER），所以 §5.2 的新列
      靠它永远加不上。

用法：
    # ① 宿主机（连宿主机 5432）
    python backend/scripts/apply_ddl.py
    python backend/scripts/apply_ddl.py --dry-run

    # ② 容器内（容器 CWD = /app/backend，只挂了 ./backend）
    docker compose exec backend python scripts/apply_ddl.py

行为：
    * **创建全幂等**：CREATE TABLE / ADD COLUMN / CREATE INDEX 均带 `IF NOT EXISTS`，
      且执行前先查系统目录，逐条打印 `[CREATE]` 或 `[SKIP]`；可重复执行无副作用；
    * **删除也幂等**（任务 3 起）：`DROP` 清单同样先查系统目录，逐条打印 `[DROP]`
      （已不存在则 `[GONE]`），语句一律带 `IF EXISTS` → 反复执行结果一致；
    * **不做列类型变更、不回填数据**；
    * **单事务**：任一步失败整体回滚，退出码非 0（不会留下半成品）；
    * **结束前自检**：创建清单必须**齐备**、删除清单必须**确实消失**，否则回滚并非 0。

覆盖范围：计划 §5.1 七张新表（llm_providers / llm_models / llm_routes / companies /
job_match_records / link_xpath_templates / link_fetch_cache）+ §5.2 新列
（job_profiles.source_url / enrich_stats、data_import_jobs.stats、users.qq / wechat）
+ B2-5 的岗位↔公司关联表 `job_company_links`（同一岗位可被多家公司在招）
+ P2 的岗位去重键生成列 `job_profiles.title_key`
+ **任务 3（2026-09-27）的多对多收口**：岗位是**角色级**的，"谁在招谁"的唯一真相是
`job_company_links` → **删掉** `job_profiles.company_id`（连同 FK `fk_job_profiles_company_id`
与索引 `ix_job_profiles_company_id`），唯一索引由
`uq_job_profiles_title_company (title_key, company_id) NULLS NOT DISTINCT`
换成 `uq_job_profiles_title_key (title_key)`。

数据库地址优先级：--database-url > 环境变量 DATABASE_URL > backend/.env（get_settings()）> 内置默认值。
Windows 控制台若中文乱码，先执行: chcp 65001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_planning"
SCHEMA = "public"

# --------------------------------------------------------------------------------------
# DDL 清单（脚本是批 2/批 3 的唯一执行路径；alembic migration 只是仓库一致性副本）
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSpec:
    name: str
    sql: str


@dataclass(frozen=True)
class ColumnSpec:
    table: str
    name: str
    sql: str


@dataclass(frozen=True)
class ConstraintSpec:
    table: str
    name: str
    sql: str


@dataclass(frozen=True)
class IndexSpec:
    name: str
    sql: str


# ── 删除清单（任务 3）────────────────────────────────────────────────────────────────
# 为什么要"能删"：脚本原先只增不减，于是 P2 留下的 `job_profiles.company_id` 一旦被
# 多对多模型废止，就**没有任何执行路径**能把它从库里去掉（alembic 基线未落库）。
# 删除同样要幂等：对象已不存在时不许报错，且要能在"全新库"上跑通。


@dataclass(frozen=True)
class DropIndexSpec:
    name: str


@dataclass(frozen=True)
class DropConstraintSpec:
    table: str
    name: str


@dataclass(frozen=True)
class DropColumnSpec:
    table: str
    name: str


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        "llm_providers",
        """
        CREATE TABLE IF NOT EXISTS llm_providers (
            id BIGSERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            base_url VARCHAR(500),
            api_key_encrypted TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_llm_providers_name UNIQUE (name)
        )
        """,
    ),
    TableSpec(
        "llm_models",
        """
        CREATE TABLE IF NOT EXISTS llm_models (
            id BIGSERIAL PRIMARY KEY,
            provider_id BIGINT NOT NULL,
            model_name VARCHAR(100) NOT NULL,
            display_name VARCHAR(100),
            kind VARCHAR(20) NOT NULL DEFAULT 'chat',
            dim INTEGER,
            temperature DOUBLE PRECISION,
            max_tokens INTEGER,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_llm_models_provider_model UNIQUE (provider_id, model_name),
            CONSTRAINT fk_llm_models_provider FOREIGN KEY (provider_id)
                REFERENCES llm_providers (id) ON DELETE CASCADE
        )
        """,
    ),
    TableSpec(
        "llm_routes",
        """
        CREATE TABLE IF NOT EXISTS llm_routes (
            id BIGSERIAL PRIMARY KEY,
            function_key VARCHAR(50) NOT NULL,
            model_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_llm_routes_function_key UNIQUE (function_key),
            CONSTRAINT fk_llm_routes_model FOREIGN KEY (model_id)
                REFERENCES llm_models (id) ON DELETE CASCADE
        )
        """,
    ),
    TableSpec(
        "companies",
        """
        CREATE TABLE IF NOT EXISTS companies (
            id BIGSERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            industry VARCHAR(100),
            city VARCHAR(50),
            job_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_companies_name UNIQUE (name)
        )
        """,
    ),
    TableSpec(
        "job_match_records",
        """
        CREATE TABLE IF NOT EXISTS job_match_records (
            id BIGSERIAL PRIMARY KEY,
            profile_snapshot_id INTEGER NOT NULL,
            job_profile_id BIGINT NOT NULL,
            "rank" INTEGER NOT NULL DEFAULT 0,
            score DOUBLE PRECISION,
            distance DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'success',
            duration_ms INTEGER,
            matched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            analysis JSONB,
            CONSTRAINT fk_job_match_records_snapshot FOREIGN KEY (profile_snapshot_id)
                REFERENCES profile_snapshots (id) ON DELETE CASCADE,
            CONSTRAINT fk_job_match_records_job_profile FOREIGN KEY (job_profile_id)
                REFERENCES job_profiles (id) ON DELETE CASCADE
        )
        """,
    ),
    TableSpec(
        "link_xpath_templates",
        """
        CREATE TABLE IF NOT EXISTS link_xpath_templates (
            id BIGSERIAL PRIMARY KEY,
            domain VARCHAR(200) NOT NULL,
            field VARCHAR(50) NOT NULL,
            xpath TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            miss_count INTEGER NOT NULL DEFAULT 0,
            last_ok_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_link_xpath_templates_domain_field UNIQUE (domain, field)
        )
        """,
    ),
    TableSpec(
        "link_fetch_cache",
        """
        CREATE TABLE IF NOT EXISTS link_fetch_cache (
            id BIGSERIAL PRIMARY KEY,
            url_hash VARCHAR(64) NOT NULL,
            url TEXT NOT NULL,
            domain VARCHAR(200),
            status_code INTEGER,
            content TEXT,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ,
            CONSTRAINT uq_link_fetch_cache_url_hash UNIQUE (url_hash)
        )
        """,
    ),
    TableSpec(
        "job_company_links",
        """
        CREATE TABLE IF NOT EXISTS job_company_links (
            id BIGSERIAL PRIMARY KEY,
            job_profile_id BIGINT NOT NULL,
            company_id BIGINT NOT NULL,
            source VARCHAR(20) NOT NULL DEFAULT 'import',
            hit_count INTEGER NOT NULL DEFAULT 1,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_job_company_links UNIQUE (job_profile_id, company_id),
            CONSTRAINT fk_job_company_links_profile FOREIGN KEY (job_profile_id)
                REFERENCES job_profiles (id) ON DELETE CASCADE,
            CONSTRAINT fk_job_company_links_company FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE
        )
        """,
    ),
)

COLUMN_SPECS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        "job_profiles",
        "source_url",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS source_url TEXT",
    ),
    ColumnSpec(
        "job_profiles",
        "enrich_stats",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS enrich_stats JSONB",
    ),
    ColumnSpec(
        "data_import_jobs",
        "stats",
        "ALTER TABLE data_import_jobs ADD COLUMN IF NOT EXISTS stats JSONB",
    ),
    ColumnSpec(
        "users",
        "qq",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS qq VARCHAR(20)",
    ),
    ColumnSpec(
        "users",
        "wechat",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS wechat VARCHAR(50)",
    ),
    # P2（2026-09-26）：岗位去重粒度改 (归一化岗位名, 公司)。
    # 用**生成列**而不是"表达式唯一索引"，原因：表达式索引要求查询里的表达式
    # 与索引定义**逐字相同**，而应用侧一律走绑定参数（`regexp_replace(title, $1, $2, $3)`），
    # 规划器无法把它匹配到带字面量的索引表达式 → 有时用不上索引。生成列则是一个普通列，
    # 查询直接 `title_key = $1`，既能用索引，也保证 Python 与 SQL 的归一化规则一致。
    ColumnSpec(
        "job_profiles",
        "title_key",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS title_key VARCHAR(200) "
        "GENERATED ALWAYS AS (lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))) STORED",
    ),
    # C1（2026-09-27，§11.1 的 ⑤）：助手消息的可视化载荷。
    # **数组**语义（一条消息可以有多个图），契约见 `app/core/chat/viz.py`；无图时 NULL。
    ColumnSpec(
        "chat_messages",
        "viz",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS viz JSONB",
    ),
    # P4a（2026-09-27）：「所需证书」此前**没有字段可落**（职业发展路线表的该列
    # 只被并进 requirements 文本）。由 `scripts/backfill_career_fields.py` 确定性回填。
    ColumnSpec(
        "job_profiles",
        "certificates",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS certificates JSONB",
    ),
    # ── 任务 1（2026-09-27）：岗位↔公司 多对多模型所需的列（**只加不删**）────────────
    # 用户构想：公司要有「规模 / 地域(省) / 城市」；岗位详情要能看到"哪些公司在招"。
    # ⚠️ 地域要**省市两级**（管理端按「先选省、再选市」级联选择，与主流地域筛选一致），
    #    所以 region(省/直辖市) 与 city(市) 分开存，且存规范化名称（不带「省/市」后缀）。
    ColumnSpec(
        "companies",
        "scale",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS scale VARCHAR(50)",
    ),
    ColumnSpec(
        "companies",
        "region",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS region VARCHAR(50)",
    ),
    # 关联表自带「招聘所在地 / 薪资 / 原始链接」：同一个岗位角色在不同公司在招时，
    # 这三项**必然不同**，所以它们属于「一次招聘」(link)，不属于「岗位角色」(profile)。
    # 地域用**招聘所在地**，而不是公司总部所在地。
    ColumnSpec(
        "job_company_links",
        "region",
        "ALTER TABLE job_company_links ADD COLUMN IF NOT EXISTS region VARCHAR(50)",
    ),
    ColumnSpec(
        "job_company_links",
        "city",
        "ALTER TABLE job_company_links ADD COLUMN IF NOT EXISTS city VARCHAR(50)",
    ),
    ColumnSpec(
        "job_company_links",
        "salary",
        "ALTER TABLE job_company_links ADD COLUMN IF NOT EXISTS salary VARCHAR(50)",
    ),
    ColumnSpec(
        "job_company_links",
        "source_url",
        "ALTER TABLE job_company_links ADD COLUMN IF NOT EXISTS source_url TEXT",
    ),
    # ── B4（2026-10-03）：分等级画像需要的三列 ─────────────────────────────────
    # 1) 薪资统计：主值区间（包络）+ 中位数区间 + 原始文本 + 条数。
    #    用户明确要求「两者都存」；`job_profiles.salary_range` 是 String(50) 存不下两份。
    ColumnSpec(
        "job_profiles",
        "salary_stats",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS salary_stats JSONB",
    ),
    # 2) 岗位综合画像卡（LLM 产物）：落库才可审计 —— 综合得对不对、丢了什么
    #    （`excluded_noise`）、模型对等级初判的异议（`level_objections`）都在这。
    #    同时存提示词版本与生成时间，便于"只重跑聚合"时对比。
    ColumnSpec(
        "job_profiles",
        "aggregate_card",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS aggregate_card JSONB",
    ),
    # 3) 原始行全量 + 抽取结果。**聚合阶段的数据来源**：`job_raw_data` 原本只有
    #    title/company/city/salary/... 十列，抽取器的 hard_skills / soft_skills /
    #    education_requirement / experience_requirement / level 与原始表的
    #    岗位编码 / 地址区县 / 公司类型 / 公司详情 / 更新日期**都没有列可放**，
    #    逐行 upsert 时就被丢掉了 —— 没地方读，聚合阶段就无从"综合"。
    ColumnSpec(
        "job_raw_data",
        "payload",
        "ALTER TABLE job_raw_data ADD COLUMN IF NOT EXISTS payload JSONB",
    ),
)


@dataclass(frozen=True)
class AlterSpec:
    """**幂等变更**（列类型加宽 / 改默认值）。

    为什么单独一类：`COLUMN_SPECS` 走 `_ensure`，**对象已存在就跳过** ——
    而 `ALTER COLUMN` 的对象一定已存在，放那边会被永远跳过（静默不生效）。
    """

    table: str
    name: str
    sql: str


#: 幂等变更清单（每次执行；语句本身可重复运行）
ALTER_SPECS: tuple[AlterSpec, ...] = (
    # B3（2026-10-03）：切片暂停闸门的状态值 `awaiting_confirmation` 有 **21 个字符**，
    # 而 `data_import_jobs.status` 建表时是 `VARCHAR(20)`（见 alembic `a1b2c3d4e5f6`）。
    # 不加宽的话，第一片跑完写状态就会 `value too long for type character varying(20)`，
    # 而且**恰好发生在最关键的"暂停等确认"那一步**。
    AlterSpec(
        "data_import_jobs",
        "status",
        "ALTER TABLE data_import_jobs ALTER COLUMN status TYPE VARCHAR(32)",
    ),
    # B4（2026-10-03）：`job_profiles.level` 必须 **NOT NULL**。
    # 理由：岗位唯一键变成了 `(title_key, level)`，而 PostgreSQL 唯一索引里
    # **NULL 互不相等** —— 可空的话两条 `level = NULL` 的同名岗位不会冲突，
    # 于是"分等级画像"又会写出重复行（P2 时代在 `(title, null)` 上踩过同一个坑）。
    #
    # 三步**必须按序**：① 先设默认值（新插入的行自动填 `不限`）
    #                 ② 回填历史 NULL（否则 SET NOT NULL 会直接失败）
    #                 ③ 再置 NOT NULL
    AlterSpec(
        "job_profiles",
        "level_default",
        "ALTER TABLE job_profiles ALTER COLUMN level SET DEFAULT '不限'",
    ),
    AlterSpec(
        "job_profiles",
        "level_backfill",
        "UPDATE job_profiles SET level = '不限' WHERE level IS NULL",
    ),
    AlterSpec(
        "job_profiles",
        "level_not_null",
        "ALTER TABLE job_profiles ALTER COLUMN level SET NOT NULL",
    ),
)

CONSTRAINT_SPECS: tuple[ConstraintSpec, ...] = (
    # 任务 3（2026-09-27）：`fk_job_profiles_company_id` 随 `company_id` 列一起删除
    # → 创建清单暂时为空（机制保留，后续新增外键照旧往这里加）。
)

INDEX_SPECS: tuple[IndexSpec, ...] = (
    IndexSpec("ix_llm_routes_model_id", "CREATE INDEX IF NOT EXISTS ix_llm_routes_model_id ON llm_routes (model_id)"),
    IndexSpec(
        "ix_companies_industry",
        "CREATE INDEX IF NOT EXISTS ix_companies_industry ON companies (industry)",
    ),
    IndexSpec(
        "ix_job_match_records_profile_snapshot_id",
        "CREATE INDEX IF NOT EXISTS ix_job_match_records_profile_snapshot_id "
        "ON job_match_records (profile_snapshot_id)",
    ),
    IndexSpec(
        "ix_job_match_records_job_profile_id",
        "CREATE INDEX IF NOT EXISTS ix_job_match_records_job_profile_id "
        "ON job_match_records (job_profile_id)",
    ),
    IndexSpec(
        "ix_job_match_records_matched_at",
        "CREATE INDEX IF NOT EXISTS ix_job_match_records_matched_at ON job_match_records (matched_at)",
    ),
    IndexSpec(
        "ix_link_fetch_cache_domain",
        "CREATE INDEX IF NOT EXISTS ix_link_fetch_cache_domain ON link_fetch_cache (domain)",
    ),
    IndexSpec(
        "ix_link_fetch_cache_expires_at",
        "CREATE INDEX IF NOT EXISTS ix_link_fetch_cache_expires_at ON link_fetch_cache (expires_at)",
    ),
    IndexSpec(
        "ix_job_company_links_company_id",
        "CREATE INDEX IF NOT EXISTS ix_job_company_links_company_id ON job_company_links (company_id)",
    ),
    # B4（2026-10-03）：岗位唯一键加上**等级** —— 「岗位名 × 等级」各一条画像。
    #
    # 为什么必须改（用户 2026-10-03 拍板，见 B4 方案）：原来只有 `(title_key)`，
    # 一个岗位名只能有一条画像；而新方案是"综合出岗位信息后按规则划分出
    # 初级/中级/高级"，**三份画像无处可放**（第二份就会撞唯一键被当成 update 覆盖）。
    #
    # ⚠️ 前置条件：`level` 必须已经 **NOT NULL**（见上面 `ALTER_SPECS` 的三步）。
    # 两者的执行顺序在本脚本里天然成立：删除清单 → 建表/加列 → ALTER → 建索引。
    IndexSpec(
        "uq_job_profiles_title_level",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_profiles_title_level "
        "ON job_profiles (title_key, level)",
    ),
)

#: 建索引前要先确认没有"归一化后重名"的岗位（否则 PG 的报错不会告诉你是哪几个）。
#: B4 起重名的判定粒度跟着唯一键一起变成 `(title_key, level)`。
_PROFILE_UNIQUE_INDEX = "uq_job_profiles_title_level"

# ── 删除清单（任务 3）：先索引/外键、后列 ──────────────────────────────────────────────
# 顺序有意为之：列上还挂着索引/外键时 PostgreSQL 会**连带删除**它们（隐式 CASCADE），
# 显式按"依赖方 → 被依赖方"写出来，日志能如实反映每一步、也不依赖隐式行为。
DROP_INDEX_SPECS: tuple[DropIndexSpec, ...] = (
    # P2 的岗位唯一键（被 `(title_key)` 单键取代）
    DropIndexSpec("uq_job_profiles_title_company"),
    # B4：任务 3 的单键唯一索引（被 `(title_key, level)` 取代）。
    # 不删的话两条索引同时存在，旧的那条会把"同名不同等级"的第二条画像顶回去。
    DropIndexSpec("uq_job_profiles_title_key"),
    # `company_id` 列上的普通索引（反正随后整列都会没）
    DropIndexSpec("ix_job_profiles_company_id"),
)

DROP_CONSTRAINT_SPECS: tuple[DropConstraintSpec, ...] = (
    DropConstraintSpec("job_profiles", "fk_job_profiles_company_id"),
)

DROP_COLUMN_SPECS: tuple[DropColumnSpec, ...] = (
    # 多对多模型下"公司归属"的唯一真相是 `job_company_links`；
    # 留着这一列 = 两个真相来源（且恒为 NULL），必须删。
    DropColumnSpec("job_profiles", "company_id"),
)


# --------------------------------------------------------------------------------------
# 系统目录探测（决定这一条是 [CREATE] 还是 [SKIP]）
# --------------------------------------------------------------------------------------


async def _table_exists(conn: AsyncConnection, name: str) -> bool:
    found = await conn.scalar(text("SELECT to_regclass(:q)::text"), {"q": f"{SCHEMA}.{name}"})
    return found is not None


async def _column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = :c)"
            ),
            {"s": SCHEMA, "t": table, "c": column},
        )
    )


async def _constraint_exists(conn: AsyncConnection, table: str, name: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conname = :n AND conrelid = to_regclass(:t))"
            ),
            {"n": name, "t": f"{SCHEMA}.{table}"},
        )
    )


async def _index_exists(conn: AsyncConnection, name: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND c.relkind = 'i' AND c.relname = :n)"
            ),
            {"s": SCHEMA, "n": name},
        )
    )


async def _duplicate_title_keys(conn: AsyncConnection) -> list[tuple[str, str, int]]:
    """归一化后重名的 `(title_key, level, 条数)`（最多 20 条）。

    只用于**建 `(title_key, level)` 唯一索引之前**的预检：PG 原生报错是
    `could not create unique index ... duplicate key value violates unique constraint`，
    既不说哪几个岗位名撞了、也不说撞了几条 → 现场只能自己再查一遍。

    ⚠️ B4 起粒度跟着唯一键一起变成 `(title_key, level)`：`title_key` 单独重复
    是**正常**的（同名不同等级本来就是三条画像），只有 `(title_key, level)` 重复才是问题。
    """
    rows = await conn.execute(
        text(
            "SELECT title_key, coalesce(level, '不限') AS lv, count(*) AS n FROM job_profiles "
            "WHERE title_key IS NOT NULL GROUP BY title_key, coalesce(level, '不限') "
            "HAVING count(*) > 1 ORDER BY n DESC, title_key ASC LIMIT 20"
        )
    )
    return [(row[0], row[1], row[2]) for row in rows.all()]


# --------------------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------------------


@dataclass
class StepResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    #: 本次真正删掉的对象（任务 3 起）
    dropped: list[str] = field(default_factory=list)
    #: 本来就不存在（全新库 / 已经删过）→ 幂等语义下属于"已就位"
    already_gone: list[str] = field(default_factory=list)
    #: dry-run 下待删的对象
    drop_planned: list[str] = field(default_factory=list)
    #: 本次执行的幂等变更（B3 起：列类型加宽等）
    altered: list[str] = field(default_factory=list)


async def _ensure(
    conn: AsyncConnection,
    kind: str,
    target: str,
    exists: bool,
    sql: str,
    dry_run: bool,
    result: StepResult,
) -> None:
    label = f"{kind} {target}"
    if exists:
        result.skipped.append(label)
        print(f"[SKIP]   {label}", flush=True)
        return
    if dry_run:
        result.planned.append(label)
        print(f"[PLAN]   {label}", flush=True)
        return
    await conn.execute(text(sql))
    result.created.append(label)
    print(f"[CREATE] {label}", flush=True)


async def _alter(
    conn: AsyncConnection,
    kind: str,
    target: str,
    sql: str,
    dry_run: bool,
    result: StepResult,
) -> None:
    """执行**幂等变更**（列类型加宽等）。

    与 `_ensure` 的关键区别：`_ensure` 在对象**已存在**时直接跳过，而 `ALTER COLUMN`
    作用的对象必然已存在 —— 塞进 `COLUMN_SPECS` 会被永远跳过、静默不生效。
    这类语句本身幂等（重复设成同一类型是空操作），所以每次执行；dry-run 只登记。
    """
    label = f"{kind} {target}"
    if dry_run:
        result.planned.append(label)
        print(f"[PLAN]   {label}", flush=True)
        return
    await conn.execute(text(sql))
    result.altered.append(label)
    print(f"[ALTER]  {label}", flush=True)


async def _drop(
    conn: AsyncConnection,
    kind: str,
    target: str,
    exists: bool,
    sql: str,
    dry_run: bool,
    result: StepResult,
) -> None:
    """删除一个对象；**已不存在**时只记一笔并继续（这就是"幂等"）。"""
    label = f"{kind} {target}"
    if not exists:
        result.already_gone.append(label)
        print(f"[GONE]   {label}", flush=True)
        return
    if dry_run:
        result.drop_planned.append(label)
        print(f"[PLAN]   DROP {label}", flush=True)
        return
    await conn.execute(text(sql))
    result.dropped.append(label)
    print(f"[DROP]   {label}", flush=True)


async def _apply_all(conn: AsyncConnection, dry_run: bool) -> StepResult:
    result = StepResult()
    # ── ① 先删（任务 3）：删列会连带删掉其上的索引/外键，所以删除永远排在创建之前，
    #    否则同一个事务里会短暂存在"旧列 + 新单键索引"两个真相。
    for spec in DROP_INDEX_SPECS:
        await _drop(
            conn,
            "index",
            spec.name,
            await _index_exists(conn, spec.name),
            f"DROP INDEX IF EXISTS {spec.name}",
            dry_run,
            result,
        )
    for spec in DROP_CONSTRAINT_SPECS:
        await _drop(
            conn,
            "constraint",
            spec.name,
            await _constraint_exists(conn, spec.table, spec.name),
            f"ALTER TABLE {spec.table} DROP CONSTRAINT IF EXISTS {spec.name}",
            dry_run,
            result,
        )
    for spec in DROP_COLUMN_SPECS:
        await _drop(
            conn,
            "column",
            f"{spec.table}.{spec.name}",
            await _column_exists(conn, spec.table, spec.name),
            f"ALTER TABLE {spec.table} DROP COLUMN IF EXISTS {spec.name}",
            dry_run,
            result,
        )

    # ── ② 建 `(title_key, level)` 唯一索引之前先预检重名
    #    （PG 原生报错说不出是哪几个岗位名 + 等级）。
    #    表都不存在时（全新库）跳过：那时的报错由后续步骤自然给出。
    if await _table_exists(conn, "job_profiles") and not await _index_exists(
        conn, _PROFILE_UNIQUE_INDEX
    ):
        duplicates = await _duplicate_title_keys(conn)
        if duplicates:
            detail = "、".join(f"{key!r}/{lv}×{count}" for key, lv, count in duplicates)
            if dry_run:
                print(
                    f"[WARN]   job_profiles 存在 (岗位名, 等级) 重复的行，"
                    f"创建 {_PROFILE_UNIQUE_INDEX} 会失败：{detail}",
                    flush=True,
                )
            else:
                raise RuntimeError(
                    f"无法把岗位唯一键换成 (title_key, level)：存在重复的 (岗位名, 等级) —— "
                    f"{detail}（先把这些行合并，再重跑本脚本）"
                )

    # ── ③ 再建（原有语义不变）
    for spec in TABLE_SPECS:
        await _ensure(
            conn, "table", spec.name, await _table_exists(conn, spec.name), spec.sql, dry_run, result
        )
    for spec in COLUMN_SPECS:
        await _ensure(
            conn,
            "column",
            f"{spec.table}.{spec.name}",
            await _column_exists(conn, spec.table, spec.name),
            spec.sql,
            dry_run,
            result,
        )
    for spec in ALTER_SPECS:
        # 幂等变更：无条件执行（对象必然已存在，`_ensure` 会跳过）
        await _alter(conn, "alter", f"{spec.table}.{spec.name}", spec.sql, dry_run, result)
    for spec in CONSTRAINT_SPECS:
        await _ensure(
            conn,
            "constraint",
            spec.name,
            await _constraint_exists(conn, spec.table, spec.name),
            spec.sql,
            dry_run,
            result,
        )
    for spec in INDEX_SPECS:
        await _ensure(
            conn, "index", spec.name, await _index_exists(conn, spec.name), spec.sql, dry_run, result
        )
    return result


async def _missing(conn: AsyncConnection) -> list[str]:
    missing: list[str] = []
    for spec in TABLE_SPECS:
        if not await _table_exists(conn, spec.name):
            missing.append(f"table {spec.name}")
    for spec in COLUMN_SPECS:
        if not await _column_exists(conn, spec.table, spec.name):
            missing.append(f"column {spec.table}.{spec.name}")
    for spec in CONSTRAINT_SPECS:
        if not await _constraint_exists(conn, spec.table, spec.name):
            missing.append(f"constraint {spec.name}")
    for spec in INDEX_SPECS:
        if not await _index_exists(conn, spec.name):
            missing.append(f"index {spec.name}")
    return missing


async def _still_present(conn: AsyncConnection) -> list[str]:
    """删除侧自检：**该没的必须真没**。

    "跑完了"不等于"删掉了" —— 少了这一步，将来有人把某个 DROP 写错名字（或漏了 `IF EXISTS`
    之外的某种情况），脚本会一路 `[DROP]`/`[GONE]` 报成功，而库里那列还在。
    """
    remaining: list[str] = []
    for spec in DROP_INDEX_SPECS:
        if await _index_exists(conn, spec.name):
            remaining.append(f"index {spec.name}（应已删除）")
    for spec in DROP_CONSTRAINT_SPECS:
        if await _constraint_exists(conn, spec.table, spec.name):
            remaining.append(f"constraint {spec.name}（应已删除）")
    for spec in DROP_COLUMN_SPECS:
        if await _column_exists(conn, spec.table, spec.name):
            remaining.append(f"column {spec.table}.{spec.name}（应已删除）")
    return remaining


async def apply_ddl(database_url: str, dry_run: bool) -> int:
    total = (
        len(TABLE_SPECS)
        + len(COLUMN_SPECS)
        + len(ALTER_SPECS)
        + len(CONSTRAINT_SPECS)
        + len(INDEX_SPECS)
        + len(DROP_INDEX_SPECS)
        + len(DROP_CONSTRAINT_SPECS)
        + len(DROP_COLUMN_SPECS)
    )
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await _apply_all(conn, dry_run)
            if dry_run:
                print(
                    f"[SUMMARY] dry-run: {len(result.planned)} 待创建 / "
                    f"{len(result.drop_planned)} 待删除 / "
                    f"{len(result.skipped) + len(result.already_gone)} 已就位"
                    f"（共 {total} 步；未落库，跳过自检）",
                    flush=True,
                )
                return 0
            missing = await _missing(conn)
            if missing:
                raise RuntimeError("自检失败，以下对象缺失：" + "、".join(missing))
            remaining = await _still_present(conn)
            if remaining:
                raise RuntimeError("自检失败，以下对象应删未删：" + "、".join(remaining))
            print(
                f"[SUMMARY] created={len(result.created)} altered={len(result.altered)} "
                f"dropped={len(result.dropped)} "
                f"already_gone={len(result.already_gone)} skipped={len(result.skipped)} "
                f"(total={total})",
                flush=True,
            )
            print(
                f"[VERIFY] 创建侧齐备：{len(TABLE_SPECS)} 表 + {len(COLUMN_SPECS)} 列 + "
                f"{len(ALTER_SPECS)} 幂等变更 + "
                f"{len(CONSTRAINT_SPECS)} 外键 + {len(INDEX_SPECS)} 索引；"
                f"删除侧已生效：{len(DROP_COLUMN_SPECS)} 列 + {len(DROP_CONSTRAINT_SPECS)} 外键 + "
                f"{len(DROP_INDEX_SPECS)} 索引",
                flush=True,
            )
            return 0
    finally:
        await engine.dispose()


def normalize_database_url(url: str) -> str:
    """把同步风格 URL 归一化到 asyncpg 驱动（本脚本用异步引擎）。"""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def resolve_database_url(cli_value: str | None) -> tuple[str, str]:
    """返回 (数据库 URL, 来源说明)。"""
    if cli_value:
        return cli_value, "--database-url"
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"], "环境变量 DATABASE_URL"
    try:
        from app.config import get_settings

        return get_settings().database_url, ".env / get_settings()"
    except Exception as exc:  # noqa: BLE001 - .env 不可用不应导致脚本崩溃
        print(
            f"[WARN] 读取 .env 失败（{type(exc).__name__}），回退到内置默认连接串；"
            "如需指定请用 --database-url",
            file=sys.stderr,
        )
        return DEFAULT_DATABASE_URL, "内置默认值（回退）"


def _mask(database_url: str) -> str:
    """隐藏连接串里的账号密码后再打印。"""
    if "@" in database_url:
        return "..." + database_url[database_url.index("@"):]
    return database_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="幂等应用批 2/批 3 的全部 DDL")
    parser.add_argument("--database-url", default=None, help="默认取 DATABASE_URL 或 backend/.env")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的步骤，不落库")
    args = parser.parse_args(argv)

    # 切到 backend/ 再读 .env：仓库根 .env 是生产模板（含 Settings 未声明的键），
    # pydantic-settings 会 extra_forbidden 直接崩；容器内 CWD 本来就是 /app/backend，等价。
    os.chdir(BACKEND_DIR)

    url, source = resolve_database_url(args.database_url)
    url = normalize_database_url(url)
    print(f"[INFO] 目标数据库 {_mask(url)}  (来源: {source})", flush=True)
    print(f"[INFO] dry_run={args.dry_run}  schema={SCHEMA}", flush=True)
    try:
        return asyncio.run(apply_ddl(url, args.dry_run))
    except Exception as exc:  # noqa: BLE001 - CLI 入口：任何异常都要给出可读信息
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
