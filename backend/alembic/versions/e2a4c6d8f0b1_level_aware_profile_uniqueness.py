"""B4: level-aware job profile uniqueness + aggregate columns

用户 2026-10-03 拍板的 B4 方案要求「先综合岗位信息，再按规则划分出初中高级岗位」，
于是 `job_profiles` 的唯一键必须从 `(title_key)` 加上**等级**这一维，
否则同名不同等级的第二份画像会撞唯一键被当成 update 覆盖。

本次改动（与 `apply_ddl.py` 的 `COLUMN_SPECS` / `ALTER_SPECS` / `INDEX_SPECS` 一一对应）：

1. 新增三列
   * `job_profiles.salary_stats`  —— 薪资统计（包络区间 + 中位数区间 + 原文 + 条数）
   * `job_profiles.aggregate_card` —— LLM 岗位综合画像卡（可审计）
   * `job_raw_data.payload`        —— 原始行全量 + 抽取结果（**聚合阶段的数据来源**）
2. `job_profiles.level` 变成 **NOT NULL DEFAULT '不限'**
   （三步按序：设默认 → 回填历史 NULL → 置 NOT NULL）
3. 唯一键 `uq_job_profiles_title_key (title_key)` → `uq_job_profiles_title_level (title_key, level)`

⚠️ 第 2 步必须在第 3 步之前：PostgreSQL 唯一索引里 **NULL 互不相等**，
`level` 可空的话两条 `level = NULL` 的同名岗位不会冲突 → 分等级等于没做。

Revision ID: e2a4c6d8f0b1
Revises: d1f2a3b4c5e6
Create Date: 2026-10-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e2a4c6d8f0b1'
down_revision: Union[str, Sequence[str], None] = 'd1f2a3b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEVEL_UNLIMITED = '不限'


def upgrade() -> None:
    # ── 1) 新增三列 ─────────────────────────────────────────────────────────
    op.add_column('job_profiles', sa.Column('salary_stats', JSONB(), nullable=True))
    op.add_column('job_profiles', sa.Column('aggregate_card', JSONB(), nullable=True))
    op.add_column('job_raw_data', sa.Column('payload', JSONB(), nullable=True))

    # ── 2) level → NOT NULL DEFAULT '不限'（顺序不可颠倒）────────────────────
    op.alter_column(
        'job_profiles',
        'level',
        existing_type=sa.String(length=20),
        existing_nullable=True,
        server_default=LEVEL_UNLIMITED,
    )
    op.execute(f"UPDATE job_profiles SET level = '{LEVEL_UNLIMITED}' WHERE level IS NULL")
    op.alter_column(
        'job_profiles',
        'level',
        existing_type=sa.String(length=20),
        existing_nullable=True,
        nullable=False,
    )

    # ── 3) 唯一键换成 (title_key, level) ────────────────────────────────────
    # 旧索引必须先删：留着它，(title_key) 上的唯一约束会把"同名不同等级"的第二条顶回去。
    op.drop_index('uq_job_profiles_title_key', table_name='job_profiles')
    op.create_index(
        'uq_job_profiles_title_level',
        'job_profiles',
        ['title_key', 'level'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_job_profiles_title_level', table_name='job_profiles')
    op.create_index(
        'uq_job_profiles_title_key', 'job_profiles', ['title_key'], unique=True
    )

    op.alter_column(
        'job_profiles', 'level', existing_type=sa.String(length=20), server_default=None
    )
    op.alter_column(
        'job_profiles',
        'level',
        existing_type=sa.String(length=20),
        existing_nullable=False,
        nullable=True,
    )

    op.drop_column('job_raw_data', 'payload')
    op.drop_column('job_profiles', 'aggregate_card')
    op.drop_column('job_profiles', 'salary_stats')
