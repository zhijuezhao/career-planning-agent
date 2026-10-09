"""add profile_snapshots / report_records（补上从未写进迁移的两张表）

Revision ID: f1a2b3c4d5e6
Revises: c7d9e1f2a3b4

背景（2026-10-09 开源发布 / CI 修复）
------------------------------------
`profile_snapshots` 与 `report_records` 这两张表**从未出现在任何迁移里**：
开发库是用 `scripts/apply_ddl.py` 直接建表的，所以 `alembic upgrade head`
在**全新库**上必挂 —— 挂在 `b8d0f2a4c6e8_add_batch2_llm_company_link_tables.py`：
它要建 `job_match_records`，而外键指向那时还不存在的 `profile_snapshots`
（CI 首次真正跑迁移时就是这么失败的）。

本迁移把两张表插到**正确的位置**：
`users`(init) → `student_profiles`(c7d9e1f2a3b4) → **本迁移** → `job_match_records`(b8d0f2a4c6e8)

两处细节：
1. 先 `inspect` 再建（幂等）：已经用 apply_ddl.py 建过表、但 alembic 版本落后的库
   不会因为"表已存在"而失败；全新库则正常建表。
2. 列定义与 `app/domain/models/profile_snapshot.py`、`report_record.py` **逐列对齐**
   （类型/可空/索引/唯一约束名），也与开发库 `\\d profile_snapshots` 实测一致。
   `embedding` 是 `vector(1024)`，依赖 init 迁移里的 `CREATE EXTENSION vector`。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "c7d9e1f2a3b4"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("profile_snapshots"):
        op.create_table(
            "profile_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_id",
                sa.BigInteger(),
                sa.ForeignKey("student_profiles.user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "form_raw_json",
                postgresql.JSONB(),
                nullable=False,
                comment="快照时的完整 resume_form",
            ),
            sa.Column(
                "five_layers_json",
                postgresql.JSONB(),
                nullable=False,
                comment="五层画像，冻结于快照",
            ),
            sa.Column(
                "six_dim_scores_json",
                postgresql.JSONB(),
                nullable=False,
                comment="六维分数，冻结于快照",
            ),
            sa.Column(
                "embedding",
                Vector(1024),
                nullable=False,
                comment="画像向量，冻结于快照",
            ),
            sa.Column("serial_no", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column(
                "matched_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="匹配完成标记：NULL=尚未匹配，非空=匹配已完成",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("user_id", "serial_no", name="profile_snapshots_user_id_serial_no_key"),
        )
        op.create_index("ix_profile_snapshots_user_id", "profile_snapshots", ["user_id"])

    if not _has_table("report_records"):
        op.create_table(
            "report_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_snapshot_id",
                sa.BigInteger(),
                sa.ForeignKey("profile_snapshots.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("serial_no", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("report_text", sa.Text(), nullable=False),
            sa.Column("word_file_path", sa.String(length=512), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("user_id", "serial_no", name="report_records_user_id_serial_no_key"),
        )
        op.create_index("ix_report_records_user_id", "report_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_report_records_user_id", table_name="report_records")
    op.drop_table("report_records")
    op.drop_index("ix_profile_snapshots_user_id", table_name="profile_snapshots")
    op.drop_table("profile_snapshots")
