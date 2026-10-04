"""widen data_import_jobs.status for the B3 slice gate

B3（2026-10-03）新增了**切片暂停闸门**状态 `awaiting_confirmation`：
一片跑完就停在这里，等管理员确认后再处理下一片。

⚠️ 这个值是 **21 个字符**，而 `data_import_jobs.status` 建表时是 `VARCHAR(20)`
（见 `a1b2c3d4e5f6_add_import_job_table`）。不加宽的话，第一片跑完写状态就会
`value too long for type character varying(20)` —— 而且恰好发生在最关键的
"暂停等确认"那一步，等于切片机制整个不可用。

同步改动：`apply_ddl.py` 的 `ALTER_SPECS`（已部署库走那条路）、
`app/domain/models/import_job.py`（ORM 列宽 32）。

Revision ID: d1f2a3b4c5e6
Revises: c9e1a3b5d7f9
Create Date: 2026-10-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd1f2a3b4c5e6'
down_revision: Union[str, Sequence[str], None] = 'c9e1a3b5d7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'data_import_jobs',
        'status',
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default='pending',
    )


def downgrade() -> None:
    op.alter_column(
        'data_import_jobs',
        'status',
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default='pending',
    )
