"""add job portrait fields to job_profiles

Revision ID: e5f7a9b1c3d2
Revises: d3f5a7b9c1e2
Create Date: 2026-09-07 23:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e5f7a9b1c3d2'
down_revision: Union[str, Sequence[str], None] = 'd3f5a7b9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_profiles',
        sa.Column('outlook', JSONB(), nullable=True, comment='岗位发展前景评估'))
    op.add_column('job_profiles',
        sa.Column('summary', sa.Text(), nullable=True, comment='岗位画像摘要'))


def downgrade() -> None:
    op.drop_column('job_profiles', 'summary')
    op.drop_column('job_profiles', 'outlook')