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
    * **全幂等**：CREATE TABLE / ADD COLUMN / CREATE INDEX 均带 `IF NOT EXISTS`，
      且执行前先查系统目录，逐条打印 `[CREATE]` 或 `[SKIP]`；可重复执行无副作用；
    * **无破坏性语句**：不含 DROP、不含列类型变更、不回填数据；
    * **单事务**：任一步失败整体回滚，退出码非 0（不会留下半成品）；
    * **结束前自检**：7 张新表 + 6 个新列 + 1 个外键 + 8 个索引必须齐备，否则回滚并非 0。

覆盖范围：计划 §5.1 七张新表（llm_providers / llm_models / llm_routes / companies /
job_match_records / link_xpath_templates / link_fetch_cache）+ §5.2 六处新列
（job_profiles.company_id / source_url / enrich_stats、data_import_jobs.stats、users.qq / wechat）
+ B2-5 的岗位↔公司关联表 `job_company_links`（同一岗位可被多家公司在招）
+ P2 的岗位去重粒度（§17）：`job_profiles.title_key` 生成列 + `uq_job_profiles_title_company`
唯一索引 `(title_key, company_id) NULLS NOT DISTINCT`。

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
        "company_id",
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS company_id BIGINT",
    ),
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
)

CONSTRAINT_SPECS: tuple[ConstraintSpec, ...] = (
    ConstraintSpec(
        "job_profiles",
        "fk_job_profiles_company_id",
        "ALTER TABLE job_profiles ADD CONSTRAINT fk_job_profiles_company_id "
        "FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE SET NULL",
    ),
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
        "ix_job_profiles_company_id",
        "CREATE INDEX IF NOT EXISTS ix_job_profiles_company_id ON job_profiles (company_id)",
    ),
    IndexSpec(
        "ix_job_company_links_company_id",
        "CREATE INDEX IF NOT EXISTS ix_job_company_links_company_id ON job_company_links (company_id)",
    ),
    # P2：岗位去重的**最终权威**。`NULLS NOT DISTINCT`（PG15+，本机 PG17）让
    # `(同名, NULL)` 也算冲突 —— 否则"没有公司列"的表会在 PG 默认的 NULL 语义下
    # 完全绕过唯一性，重复插入无人拦。
    IndexSpec(
        "uq_job_profiles_title_company",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_profiles_title_company "
        "ON job_profiles (title_key, company_id) NULLS NOT DISTINCT",
    ),
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


# --------------------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------------------


@dataclass
class StepResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)


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


async def _apply_all(conn: AsyncConnection, dry_run: bool) -> StepResult:
    result = StepResult()
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


async def apply_ddl(database_url: str, dry_run: bool) -> int:
    total = len(TABLE_SPECS) + len(COLUMN_SPECS) + len(CONSTRAINT_SPECS) + len(INDEX_SPECS)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await _apply_all(conn, dry_run)
            if dry_run:
                print(
                    f"[SUMMARY] dry-run: {len(result.planned)} 待创建 / {len(result.skipped)} 已存在"
                    f"（共 {total} 步；未落库，跳过自检）",
                    flush=True,
                )
                return 0
            missing = await _missing(conn)
            if missing:
                raise RuntimeError("自检失败，以下对象缺失：" + "、".join(missing))
            print(
                f"[SUMMARY] created={len(result.created)} skipped={len(result.skipped)} (total={total})",
                flush=True,
            )
            print(
                f"[VERIFY] {len(TABLE_SPECS)} 表 + {len(COLUMN_SPECS)} 列 + "
                f"{len(CONSTRAINT_SPECS)} 外键 + {len(INDEX_SPECS)} 索引齐备",
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
