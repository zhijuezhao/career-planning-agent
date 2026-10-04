#!/usr/bin/env python
"""给**缺少岗位向量**的 `job_profiles` 补 `job_match_embeddings`（零 LLM，只花 embedding）。

为什么需要这个脚本（2026-10-04 实测事故）
----------------------------------------
学生端"选择岗位"一步提示：

    岗位库还没有可用的岗位向量，或本次匹配没有返回结果……

而库里的真实情况是：`job_profiles` 有 87 条画像、`job_match_embeddings` **0 行**。
根因是**写入方缺失**：`embed_job()` 原先只有两个调用点 ——
管理员手动新建岗位（`admin/jobs.py` 的 `create_job`）和单人重建
（`POST /admin/jobs/{id}/re-embed`）。**B1–B5 的导入链路（persist / 聚合）从不写向量**，
所以"导入了一整张表"并不会让匹配可用。

`aggregate_roles()` 现在会在每组落到 `job_profiles` 后顺手写向量，
所以**新导入**会自动带上；本脚本负责两类存量数据：
1. 该修复之前导入的画像（例如本次那 87 条）；
2. 向量写入时失败/被清掉的画像。

用法::

    # 只补缺失的（默认；已存在且内容一致的会跳过）
    docker exec -e PYTHONPATH=/app/backend -w /app/backend career_backend \
        python scripts/backfill_job_embeddings.py

    # 全部重算（换 embedding 模型/维度后必须这样跑一遍）
    ... python scripts/backfill_job_embeddings.py --all

    # 只看看要处理哪些，不写库
    ... python scripts/backfill_job_embeddings.py --dry-run

退出码：0 = 全部成功；1 = 有失败（逐条原因会打印）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.matching.job_matcher import build_job_text, embed_job  # noqa: E402
from app.domain.models.job import JobProfile  # noqa: E402
from app.domain.models.vector import JobMatchEmbedding  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402
from sqlalchemy import select  # noqa: E402


@dataclass
class BackfillStats:
    total: int = 0
    embedded: int = 0
    skipped_current: int = 0
    failed: list[str] = field(default_factory=list)


async def backfill(all_profiles: bool) -> BackfillStats:
    stats = BackfillStats()
    async with async_session_factory() as session:
        profiles = (await session.execute(select(JobProfile).order_by(JobProfile.id))).scalars().all()
        existing = {
            row.job_profile_id: row
            for row in (await session.execute(select(JobMatchEmbedding))).scalars().all()
        }

        for profile in profiles:
            stats.total += 1
            text = build_job_text(profile)
            if not text.strip():
                stats.failed.append(f"id={profile.id} {profile.title!r}：岗位文本为空，跳过")
                continue

            row = existing.get(profile.id)
            # 内容没变的不用重算（embedding 是按内容算的，重算纯浪费）
            if row is not None and not all_profiles and row.content == text:
                stats.skipped_current += 1
                continue

            result = await embed_job(profile.id, session=session)
            if result is None:
                stats.failed.append(f"id={profile.id} {profile.title!r}：embed 失败（见后端日志 warning）")
            else:
                stats.embedded += 1

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给缺少岗位向量的画像补 job_match_embeddings")
    parser.add_argument("--all", action="store_true", help="全部重算（换向量模型后用）")
    parser.add_argument("--dry-run", action="store_true", help="只列出要处理的画像，不写库")
    args = parser.parse_args(argv)

    if args.dry_run:
        async def _list() -> None:
            async with async_session_factory() as session:
                profiles = (
                    await session.execute(select(JobProfile).order_by(JobProfile.id))
                ).scalars().all()
                existing = {
                    row.job_profile_id: row
                    for row in (await session.execute(select(JobMatchEmbedding))).scalars().all()
                }
                missing = [p for p in profiles if p.id not in existing]
                stale = [
                    p for p in profiles
                    if (row := existing.get(p.id)) is not None and row.content != build_job_text(p)
                ]
                print(f"[dry-run] 画像 {len(profiles)} 条；缺向量 {len(missing)} 条；内容已变需重算 {len(stale)} 条")
                for profile in missing[:20]:
                    print(f"  缺向量 | id={profile.id} | {profile.title} | {profile.level}")
                for profile in stale[:20]:
                    print(f"  内容变 | id={profile.id} | {profile.title} | {profile.level}")

        asyncio.run(_list())
        return 0

    stats = asyncio.run(backfill(args.all))
    print(
        f"[SUMMARY] 画像 {stats.total} 条 → 写入 {stats.embedded} 条、"
        f"已是最新 {stats.skipped_current} 条、失败 {len(stats.failed)} 条"
    )
    for line in stats.failed:
        print(f"[FAIL] {line}", file=sys.stderr)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
