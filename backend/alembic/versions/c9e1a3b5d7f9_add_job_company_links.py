"""add job_company_links (position <-> company many-to-many)

Revision ID: c9e1a3b5d7f9
Revises: b8d0f2a4c6e8
Create Date: 2026-09-25 21:00:00.000000

B2-5：`job_profiles` 仍按岗位名去重（画像/匹配语义不变），但"某个岗位有哪些公司在招"是
多对多 —— 该表记录每个 (岗位, 公司) 组合。`companies.job_count` 改为按本表重算
（count(distinct job_profile_id)），不再因同岗多公司互相覆盖而变陈旧。

与 `backend/scripts/apply_ddl.py` 等价；开发库实际走脚本（方案 A），本文件供仓库一致性。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9e1a3b5d7f9'
down_revision: Union[str, Sequence[str], None] = 'b8d0f2a4c6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_company_links',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('job_profile_id', sa.BigInteger(), nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='import'),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_profile_id'], ['job_profiles.id'],
                                name='fk_job_company_links_profile', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'],
                                name='fk_job_company_links_company', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_profile_id', 'company_id', name='uq_job_company_links'),
    )
    op.create_index('ix_job_company_links_company_id', 'job_company_links', ['company_id'])


def downgrade() -> None:
    op.drop_index('ix_job_company_links_company_id', table_name='job_company_links')
    op.drop_table('job_company_links')
