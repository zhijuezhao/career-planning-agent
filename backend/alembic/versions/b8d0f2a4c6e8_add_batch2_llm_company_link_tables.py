"""add batch2 tables (llm config center / companies / match records / link enrich)

Revision ID: b8d0f2a4c6e8
Revises: c7d9e1f2a3b4
Create Date: 2026-09-23 18:00:00.000000

批 2/批 3 的 DDL：7 张新表 + 6 处新列（全部可空新增，向后兼容，不回填）。
本文件只为**仓库一致性/未来新环境**；开发库没有 alembic_version 基线，
实际落库走 `backend/scripts/apply_ddl.py`（幂等，见计划 §7 方案 A）。
两份内容等价，若日后改动请同步修改。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b8d0f2a4c6e8'
down_revision: Union[str, Sequence[str], None] = 'c7d9e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- 7 张新表 ----------------
    op.create_table(
        'llm_providers',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('base_url', sa.String(length=500), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_llm_providers_name'),
    )

    op.create_table(
        'llm_models',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('provider_id', sa.BigInteger(), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='chat'),
        sa.Column('dim', sa.Integer(), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'],
                                name='fk_llm_models_provider', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_id', 'model_name', name='uq_llm_models_provider_model'),
    )

    op.create_table(
        'llm_routes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('function_key', sa.String(length=50), nullable=False),
        sa.Column('model_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['llm_models.id'],
                                name='fk_llm_routes_model', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('function_key', name='uq_llm_routes_function_key'),
    )

    op.create_table(
        'companies',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('industry', sa.String(length=100), nullable=True),
        sa.Column('city', sa.String(length=50), nullable=True),
        sa.Column('job_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_companies_name'),
    )

    op.create_table(
        'job_match_records',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        # profile_snapshots.id 是 integer（不是 bigint），外键列必须同型
        sa.Column('profile_snapshot_id', sa.Integer(), nullable=False),
        sa.Column('job_profile_id', sa.BigInteger(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('distance', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='success'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('matched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('analysis', JSONB(), nullable=True),
        sa.ForeignKeyConstraint(['profile_snapshot_id'], ['profile_snapshots.id'],
                                name='fk_job_match_records_snapshot', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_profile_id'], ['job_profiles.id'],
                                name='fk_job_match_records_job_profile', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'link_xpath_templates',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('domain', sa.String(length=200), nullable=False),
        sa.Column('field', sa.String(length=50), nullable=False),
        sa.Column('xpath', sa.Text(), nullable=False),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('miss_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain', 'field', name='uq_link_xpath_templates_domain_field'),
    )

    op.create_table(
        'link_fetch_cache',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('url_hash', sa.String(length=64), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('domain', sa.String(length=200), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url_hash', name='uq_link_fetch_cache_url_hash'),
    )

    # ---------------- 6 处新列（全部可空新增） ----------------
    op.add_column('job_profiles', sa.Column('company_id', sa.BigInteger(), nullable=True))
    op.add_column('job_profiles', sa.Column('source_url', sa.Text(), nullable=True))
    op.add_column('job_profiles', sa.Column('enrich_stats', JSONB(), nullable=True))
    op.add_column('data_import_jobs', sa.Column('stats', JSONB(), nullable=True))
    op.add_column('users', sa.Column('qq', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('wechat', sa.String(length=50), nullable=True))

    op.create_foreign_key('fk_job_profiles_company_id', 'job_profiles', 'companies',
                          ['company_id'], ['id'], ondelete='SET NULL')

    # ---------------- 索引 ----------------
    op.create_index('ix_llm_routes_model_id', 'llm_routes', ['model_id'])
    op.create_index('ix_companies_industry', 'companies', ['industry'])
    op.create_index('ix_job_match_records_profile_snapshot_id', 'job_match_records', ['profile_snapshot_id'])
    op.create_index('ix_job_match_records_job_profile_id', 'job_match_records', ['job_profile_id'])
    op.create_index('ix_job_match_records_matched_at', 'job_match_records', ['matched_at'])
    op.create_index('ix_link_fetch_cache_domain', 'link_fetch_cache', ['domain'])
    op.create_index('ix_link_fetch_cache_expires_at', 'link_fetch_cache', ['expires_at'])
    op.create_index('ix_job_profiles_company_id', 'job_profiles', ['company_id'])


def downgrade() -> None:
    op.drop_index('ix_job_profiles_company_id', table_name='job_profiles')
    op.drop_index('ix_link_fetch_cache_expires_at', table_name='link_fetch_cache')
    op.drop_index('ix_link_fetch_cache_domain', table_name='link_fetch_cache')
    op.drop_index('ix_job_match_records_matched_at', table_name='job_match_records')
    op.drop_index('ix_job_match_records_job_profile_id', table_name='job_match_records')
    op.drop_index('ix_job_match_records_profile_snapshot_id', table_name='job_match_records')
    op.drop_index('ix_companies_industry', table_name='companies')
    op.drop_index('ix_llm_routes_model_id', table_name='llm_routes')

    op.drop_constraint('fk_job_profiles_company_id', 'job_profiles', type_='foreignkey')
    op.drop_column('users', 'wechat')
    op.drop_column('users', 'qq')
    op.drop_column('data_import_jobs', 'stats')
    op.drop_column('job_profiles', 'enrich_stats')
    op.drop_column('job_profiles', 'source_url')
    op.drop_column('job_profiles', 'company_id')

    op.drop_table('link_fetch_cache')
    op.drop_table('link_xpath_templates')
    op.drop_table('job_match_records')
    op.drop_table('companies')
    op.drop_table('llm_routes')
    op.drop_table('llm_models')
    op.drop_table('llm_providers')
