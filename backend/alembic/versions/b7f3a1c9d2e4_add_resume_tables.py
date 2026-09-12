"""add_resume_tables

Revision ID: b7f3a1c9d2e4
Revises: ca67e30eea59
Create Date: 2026-09-06 10:00:00.000000

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7f3a1c9d2e4'
down_revision: Union[str, Sequence[str], None] = 'ca67e30eea59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('resumes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('parsed_data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='uploaded', nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('profile_id', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['ability_profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_match_embeddings',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('profile_id', sa.BigInteger(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['ability_profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute(
        "CREATE INDEX ix_user_match_embeddings_embedding "
        "ON user_match_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.create_unique_constraint(
        "uq_ability_profile_user_direction",
        "ability_profiles",
        ["user_id", "direction_tag"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_ability_profile_user_direction", "ability_profiles", type_="unique")
    op.execute("DROP INDEX IF EXISTS ix_user_match_embeddings_embedding")
    op.drop_table('user_match_embeddings')
    op.drop_table('resumes')
