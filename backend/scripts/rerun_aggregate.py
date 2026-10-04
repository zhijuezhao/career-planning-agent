#!/usr/bin/env python
"""只重跑「阶段 8」岗位聚合 —— 不重跑抽取、不重跑切片处理。

为什么单独给一个脚本（用户 2026-10-03 拍板要的）：

* 聚合是**幂等**的：输入只有 `job_raw_data`（原始数据），输出只有 `job_profiles`；
* 抽取每行 1 次 LLM，而聚合每组 2 次 —— 改了聚合提示词/规则后重跑，
  完全没必要把 487 次抽取再烧一遍；
* 出了问题时也可以先关 `IMPORT_AGGREGATE_ENABLED`、让导入只保证原始数据，
  事后用本脚本补画像。

用法::

    # 全部岗位重跑（默认 dry-run？不 —— 默认真写，见 --dry-run）
    python -m scripts.rerun_aggregate

    # 只预览（跑 LLM 但不落库），先看综合质量
    python -m scripts.rerun_aggregate --dry-run

    # 只重算指定岗位（按归一化后的岗位名匹配，大小写/空白不敏感）
    python -m scripts.rerun_aggregate --title "java" --title "软件测试"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.dedup_keys import normalise_title  # noqa: E402
from app.domain.services.job_aggregate_service import aggregate_roles  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402


async def _run(titles: set[str] | None, dry_run: bool) -> int:
    async with async_session_factory() as session:
        stats = await aggregate_roles(session, titles=titles, dry_run=dry_run)

    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
    if stats.get("failed"):
        print(
            f"\n⚠️  {stats['failed']}/{stats['groups']} 组失败（原始数据不受影响，可重跑）",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只重跑岗位聚合（阶段 8）")
    parser.add_argument(
        "--title",
        action="append",
        default=None,
        help="只重算这些岗位名（可重复；按归一化后的名字匹配）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="跑 LLM 但不落库（先看综合质量）",
    )
    args = parser.parse_args(argv)

    titles = {normalise_title(t) for t in args.title} if args.title else None
    if titles:
        print(f"只重算：{sorted(titles)}", flush=True)
    else:
        print("重算全部岗位", flush=True)

    return asyncio.run(_run(titles, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
