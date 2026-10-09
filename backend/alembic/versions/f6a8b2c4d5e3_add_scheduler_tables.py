"""add scheduler tables

Revision ID: f6a8b2c4d5e3
Revises: e5f7a9b1c3d2
Create Date: 2026-09-08 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'f6a8b2c4d5e3'
down_revision: Union[str, Sequence[str], None] = 'e5f7a9b1c3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('job_update_schedules',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source_key', sa.String(length=200), nullable=False),
        sa.Column('source_name', sa.String(length=200), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False, server_default='web'),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('industry', sa.String(length=100), nullable=True),
        sa.Column('keywords', sa.String(length=300), nullable=True),
        sa.Column('interval_days', sa.Float(), nullable=False, server_default='7.0'),
        sa.Column('min_interval_days', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('max_interval_days', sa.Float(), nullable=False, server_default='60.0'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_change_rate', sa.Float(), nullable=True),
        sa.Column('last_item_count', sa.Integer(), nullable=True),
        sa.Column('consecutive_no_change', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('job_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_key', name='uq_job_update_schedule_source_key'),
    )
    op.create_index('ix_job_update_schedules_source_key', 'job_update_schedules', ['source_key'])
    op.create_index('ix_job_update_schedules_industry', 'job_update_schedules', ['industry'])
    op.create_index('ix_job_update_schedules_active', 'job_update_schedules', ['is_active'])

    op.create_table('industry_reports',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('industry', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sections', JSONB(), nullable=True),
        sa.Column('source_urls', JSONB(), nullable=True),
        sa.Column('keywords', sa.String(length=300), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('is_ai_enriched', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('report_hash', sa.String(length=64), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_industry_reports_industry', 'industry_reports', ['industry'])
    op.create_index('ix_industry_reports_generated_at', 'industry_reports', ['generated_at'])


def downgrade() -> None:
    op.drop_index('ix_industry_reports_generated_at', table_name='industry_reports')
    op.drop_index('ix_industry_reports_industry', table_name='industry_reports')
    op.drop_table('industry_reports')

    op.drop_index('ix_job_update_schedules_active', table_name='job_update_schedules')
    op.drop_index('ix_job_update_schedules_industry', table_name='job_update_schedules')
    op.drop_index('ix_job_update_schedules_source_key', table_name='job_update_schedules')
    op.drop_table('job_update_schedules')
