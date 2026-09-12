"""add dimension scoring tables

Revision ID: d3f5a7b9c1e2
Revises: b7f3a1c9d2e4
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd3f5a7b9c1e2'
down_revision: Union[str, Sequence[str], None] = 'b7f3a1c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('dimension_scores',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('profile_type', sa.String(length=20), nullable=False),
        sa.Column('profile_id', sa.BigInteger(), nullable=False),
        sa.Column('top_dimension', sa.String(length=50), nullable=False),
        sa.Column('sub_dimension', sa.String(length=50), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'profile_type', 'profile_id', 'top_dimension', 'sub_dimension',
            name='uq_dimension_score_profile_dim',
        ),
    )
    op.create_index('ix_dimension_scores_profile', 'dimension_scores', ['profile_type', 'profile_id'])

    op.create_table('dimension_weights',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('job_category', sa.String(length=50), nullable=False),
        sa.Column('top_dimension', sa.String(length=50), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'job_category', 'top_dimension',
            name='uq_dimension_weight_category_dim',
        ),
    )

    # Seed default weight configurations (3 job categories x 6 dimensions = 18 rows)
    op.execute("""
        INSERT INTO dimension_weights (job_category, top_dimension, weight) VALUES
        ('技术研发岗', '专业技术能力', 0.30),
        ('技术研发岗', '实践经验背景', 0.25),
        ('技术研发岗', '通用软素质',   0.15),
        ('技术研发岗', '职业匹配度',   0.10),
        ('技术研发岗', '成长潜力',     0.15),
        ('技术研发岗', '基础资质条件', 0.05),
        ('产品/运营岗', '专业技术能力', 0.15),
        ('产品/运营岗', '实践经验背景', 0.25),
        ('产品/运营岗', '通用软素质',   0.25),
        ('产品/运营岗', '职业匹配度',   0.15),
        ('产品/运营岗', '成长潜力',     0.15),
        ('产品/运营岗', '基础资质条件', 0.05),
        ('管培/销售岗', '专业技术能力', 0.10),
        ('管培/销售岗', '实践经验背景', 0.20),
        ('管培/销售岗', '通用软素质',   0.25),
        ('管培/销售岗', '职业匹配度',   0.20),
        ('管培/销售岗', '成长潜力',     0.20),
        ('管培/销售岗', '基础资质条件', 0.05)
    """)

    # Drop obsolete columns from ability_profiles
    op.drop_column('ability_profiles', 'derived_scores')
    op.drop_column('ability_profiles', 'completeness_score')


def downgrade() -> None:
    # Restore dropped columns
    op.add_column('ability_profiles',
        sa.Column('completeness_score', sa.Float(), server_default='0.0', nullable=False))
    op.add_column('ability_profiles',
        sa.Column('derived_scores', sa.JSON(), server_default='{}', nullable=False))

    op.drop_table('dimension_weights')
    op.drop_index('ix_dimension_scores_profile', table_name='dimension_scores')
    op.drop_table('dimension_scores')
