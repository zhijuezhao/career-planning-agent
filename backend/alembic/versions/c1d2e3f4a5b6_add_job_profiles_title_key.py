"""add job_profiles.title_key（补上迁移里从来没有的列）

Revision ID: c1d2e3f4a5b6
Revises: d1f2a3b4c5e6

背景（2026-10-09 开源发布 / CI 修复）
------------------------------------
`job_profiles.title_key` 只在 `apply_ddl.py` 里存在，**没有任何迁移创建过它**。
而紧随其后的 `e2a4c6d8f0b1`（B4 分等级唯一键）要建
`uq_job_profiles_title_level (title_key, level)` —— 全新库跑到那里就抛
`column "title_key" does not exist`，整条迁移链崩掉（CI 实测）。

所以这里把该列补在 `e2a4c6d8f0b1` **之前**。

⚠️ 它是 **GENERATED 生成列**（模型里 `Computed(_TITLE_KEY_EXPR, persisted=True)`），
不能建成普通列 —— 建错的话 `title_key` 永远是 NULL，唯一索引失效，
所有"标题归一化 / 同名去重"用例全红（2026-10-09 实测：28 个失败里有 15 个是这个原因）。
表达式与 `app/core/dedup_keys.py:TITLE_KEY_SQL`、`apply_ddl.py`、开发库实测完全一致。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "d1f2a3b4c5e6"
branch_labels = None
depends_on = None

#: 生成列表达式（冻结在此，避免迁移依赖可变的应用代码；
#: 与 app/core/dedup_keys.py 的 TITLE_KEY_SQL 一字不差）
TITLE_KEY_EXPR = "lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))"


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "title_key" not in _columns("job_profiles"):
        op.add_column(
            "job_profiles",
            sa.Column(
                "title_key",
                sa.String(length=200),
                sa.Computed(TITLE_KEY_EXPR, persisted=True),
            ),
        )


def downgrade() -> None:
    if "title_key" in _columns("job_profiles"):
        op.drop_column("job_profiles", "title_key")
