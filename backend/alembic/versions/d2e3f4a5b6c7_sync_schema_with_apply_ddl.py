"""sync schema with apply_ddl.py（把迁移链的终态对齐到开发库真实 schema）

Revision ID: d2e3f4a5b6c7
Revises: e2a4c6d8f0b1

背景（2026-10-09 开源发布 / CI 修复）
------------------------------------
本仓库的历史遗留：**开发库不是 alembic 建的**（没有 `alembic_version` 表），
而是 `backend/scripts/apply_ddl.py` 直接改表。作者在 `b8d0f2a4c6e8` 的 docstring
里也写了"迁移只为仓库一致性/未来新环境"—— 于是迁移链从来没有在全新库上验证过，
实测在 CI（全新库）上连续挂在三处：缺表、缺列、多余列。

本迁移是**最后一步对齐**，把迁移建出的 schema 收敛到"开发库 / 模型 / 测试断言"
三者一致的终态。所有操作都先 `inspect` 再执行（幂等），因此：

* 全新库（CI）：补齐 12 列、删掉 19 个已废弃列；
* 已用 apply_ddl.py 建好的老库：本来就是这个终态，全部跳过，不报错。

## 补齐（13 列，其中 title_key 已由 c1d2e3f4a5b6、salary_stats/
## aggregate_card/payload 由 e2a4c6d8f0b1 补过，这里是防御性兜底）
  job_profiles    : title_key / certificates / salary_stats / aggregate_card
  job_raw_data    : payload
  chat_messages   : viz
  companies       : region / scale
  job_company_links: region / city / salary / source_url
  student_profiles: resume_form

## 删除（19 列：模型里已删除、开发库里也早就不存在的"历史画像列"）
  users           : real_name / age / gender / school / major / degree / grade / grad_year
  student_profiles: certificates / internship / project / skills / self_intro /
                    target_industry / target_position / other_experience / weekly_hours
  job_profiles    : company_id（任务 3 已把归属改到 job_company_links）
  resumes         : profile_id（画像单一权威改为 student_profiles.resume_form）

⚠️ 注意保留旧**表**（ability_profiles / career_reports / job_matches /
user_feedbacks / growth_paths / growth_plans / ai_configs / user_match_embeddings）：
`tests/test_core/test_database.py` 明确断言它们存在。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d2e3f4a5b6c7"
down_revision = "e2a4c6d8f0b1"
branch_labels = None
depends_on = None

#: `job_profiles.title_key` 的生成列表达式（见 c1d2e3f4a5b6；这里只做防御性兜底）
TITLE_KEY_EXPR = "lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))"


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop(table: str, column: str) -> None:
    if column in _columns(table):
        op.drop_column(table, column)


def upgrade() -> None:
    # ── 1) 补齐缺失列 ────────────────────────────────────────────────────────
    # 注意 title_key 是**生成列**（不是普通列）：c1d2e3f4a5b6 已建，这里是兜底。
    _add(
        "job_profiles",
        sa.Column(
            "title_key",
            sa.String(length=200),
            sa.Computed(TITLE_KEY_EXPR, persisted=True),
        ),
    )
    _add("job_profiles", sa.Column("certificates", JSONB(), nullable=True))
    _add("job_profiles", sa.Column("salary_stats", JSONB(), nullable=True))
    _add("job_profiles", sa.Column("aggregate_card", JSONB(), nullable=True))
    _add("job_raw_data", sa.Column("payload", JSONB(), nullable=True))
    _add("chat_messages", sa.Column("viz", JSONB(), nullable=True))
    _add("companies", sa.Column("region", sa.String(length=50), nullable=True))
    _add("companies", sa.Column("scale", sa.String(length=50), nullable=True))
    _add("job_company_links", sa.Column("region", sa.String(length=50), nullable=True))
    _add("job_company_links", sa.Column("city", sa.String(length=50), nullable=True))
    _add("job_company_links", sa.Column("salary", sa.String(length=50), nullable=True))
    _add("job_company_links", sa.Column("source_url", sa.Text(), nullable=True))

    # student_profiles.resume_form 是 NOT NULL：先带 server_default 加列（空表/老表都安全），
    # 再把 server_default 去掉，使 DDL 与开发库/模型完全一致。
    if "resume_form" not in _columns("student_profiles"):
        op.add_column(
            "student_profiles",
            sa.Column("resume_form", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        )
        op.alter_column("student_profiles", "resume_form", server_default=None)

    # ── 2) 删掉已废弃的历史列 ────────────────────────────────────────────────
    for column in (
        "real_name",
        "age",
        "gender",
        "school",
        "major",
        "degree",
        "grade",
        "grad_year",
    ):
        _drop("users", column)

    for column in (
        "certificates",
        "internship",
        "project",
        "skills",
        "self_intro",
        "target_industry",
        "target_position",
        "other_experience",
        "weekly_hours",
    ):
        _drop("student_profiles", column)

    _drop("job_profiles", "company_id")
    _drop("resumes", "profile_id")


def downgrade() -> None:
    # 反向恢复：把补的列删掉、把废弃列加回来（类型与原迁移一致，便于回滚到旧版本）。
    for column in ("title_key", "certificates", "salary_stats", "aggregate_card"):
        _drop("job_profiles", column)
    _drop("job_raw_data", "payload")
    _drop("chat_messages", "viz")
    for column in ("region", "scale"):
        _drop("companies", column)
    for column in ("region", "city", "salary", "source_url"):
        _drop("job_company_links", column)
    _drop("student_profiles", "resume_form")

    _add("job_profiles", sa.Column("company_id", sa.BigInteger(), nullable=True))
    _add("resumes", sa.Column("profile_id", sa.BigInteger(), nullable=True))
    for column in (
        "certificates",
        "internship",
        "project",
        "skills",
        "self_intro",
        "target_industry",
        "target_position",
        "other_experience",
        "weekly_hours",
    ):
        column_type = sa.Integer() if column == "weekly_hours" else JSONB()
        _add("student_profiles", sa.Column(column, column_type, nullable=True))
    for column in ("real_name", "gender", "school", "major", "degree", "grade"):
        _add("users", sa.Column(column, sa.String(length=50), nullable=True))
    _add("users", sa.Column("age", sa.Integer(), nullable=True))
    _add("users", sa.Column("grad_year", sa.Integer(), nullable=True))
