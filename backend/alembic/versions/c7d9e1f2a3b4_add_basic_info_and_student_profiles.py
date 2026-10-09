"""add basic info to users and create student_profiles

Revision ID: c7d9e1f2a3b4
Revises: a1b2c3d4e5f6
Create Date: 2026-09-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'c7d9e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('real_name', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('age', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('gender', sa.String(length=10), nullable=True))
    op.add_column('users', sa.Column('school', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('major', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('degree', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('grade', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('grad_year', sa.Integer(), nullable=True))

    op.create_table(
        'student_profiles',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('internship', sa.Text(), nullable=True),
        sa.Column('project', sa.Text(), nullable=True),
        sa.Column('other_experience', sa.Text(), nullable=True),
        sa.Column('skills', JSONB(), nullable=True),
        sa.Column('certificates', JSONB(), nullable=True),
        sa.Column('self_intro', sa.Text(), nullable=True),
        sa.Column('target_industry', sa.Text(), nullable=True),
        sa.Column('target_position', sa.Text(), nullable=True),
        sa.Column('weekly_hours', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # 2026-10-09 修复：原先是 NO ACTION，而 app 的 delete_user 只显式删
        # chat_sessions/chat_messages/resumes，`student_profiles` 靠**级联**清理
        # → 全新库上删用户抛 FK 违约（实测 test_delete_user_with_dependents 失败）。
        # 开发库该外键本就是 ON DELETE CASCADE，这里保持一致。
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], name='fk_student_profiles_user_id', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('user_id', name='pk_student_profiles'),
    )
    op.create_index('ix_student_profiles_user_id', 'student_profiles', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_student_profiles_user_id', table_name='student_profiles')
    op.drop_table('student_profiles')
    op.drop_column('users', 'real_name')
    op.drop_column('users', 'age')
    op.drop_column('users', 'gender')
    op.drop_column('users', 'school')
    op.drop_column('users', 'major')
    op.drop_column('users', 'degree')
    op.drop_column('users', 'grade')
    op.drop_column('users', 'grad_year')
