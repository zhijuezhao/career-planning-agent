"""add import job table

Revision ID: a1b2c3d4e5f6
Revises: f6a8b2c4d5e3
Create Date: 2026-09-09 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f6a8b2c4d5e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('data_import_jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('total_rows', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('processed_rows', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('success_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('error_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('errors', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_data_import_jobs'),
    )
    op.create_index('ix_data_import_jobs_status', 'data_import_jobs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_data_import_jobs_status', table_name='data_import_jobs')
    op.drop_table('data_import_jobs')
