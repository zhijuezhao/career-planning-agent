"""把职业发展路线表的「岗位晋升 / 换岗方向 / 所需证书」**确定性回填**进 `job_profiles`。

背景（2026-09-27 实测）
----------------------
`#853` 导入的 82 行是**职业发展路线表**。它的额外列按 `schema_detect.MERGE_RULES` 的
设计并进了 `job_raw_data` 的 `description` / `requirements` 自由文本，指望 portrait 的 LLM
再抽成结构化字段。但 portrait 对其中约 73 行**静默失败**（`portrait_builder` 的 `except`
返回默认值），结果：

| 源文本里有 | 画像里 |
|---|---|
| `岗位晋升：` 84 行 | `career_path` **0/82** |
| `换岗方向：` 84 行 | `transition_paths` **8/82** |
| `所需证书：` 84 行 | **没有字段可落**（本次加了 `certificates` 列） |

这些内容就是 `A / B / C` 列表 → **不需要 LLM**。本脚本用 `core/job_agent/career_fields.py`
的确定性拆分器回填，**0 token、可反复重跑**。

设计约定（与 `cleanup_test_data.py` 一致）
------------------------------------------
- **默认 dry-run**，必须显式 `--apply` 才写库；
- 写之前把**每一处改动**（旧值/新值）导出 CSV 到**仓库外**（仓库内目录直接拒跑）；
- **单事务**提交；事务内先自检再 commit；
- 默认**只填空**（目标已是 JSON null / 空列表才算空）→ 幂等，且以后重跑 portrait
  也不会被本脚本覆盖；要强制覆盖用 `--overwrite`；
- 解析结果可疑（某项过长 / 残留另一个分隔符）时**跳过该字段并告警**，绝不写脏数据。

用法::

    python backend/scripts/backfill_career_fields.py              # 看报告，不写库
    python backend/scripts/backfill_career_fields.py --apply      # 写入（先备份到仓库外）
    python backend/scripts/backfill_career_fields.py --apply --overwrite
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.job_agent.career_fields import (
    FIELD_LABELS,
    extract_career_fields,
    looks_suspicious,
)
from app.domain.models.job import JobProfile, JobRawData
from app.infrastructure.database import async_session_factory
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

FIELDS: tuple[str, ...] = ("career_path", "transition_paths", "certificates")

#: 仓库根（用来拒绝"把备份写进仓库"）
REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_empty(value: Any) -> bool:
    """JSONB 语义下的"空"：SQL NULL / JSON null（→ Python None）/ 空容器 / 空串。"""
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


@dataclass
class Change:
    profile_id: int
    title: str
    field_name: str
    old: Any
    new: list[str]


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    #: 每个字段能解析出内容的 profile 数（用于自检期望值）
    expected: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    #: 已有内容、被跳过的 profile 数（默认 fill-only 时）
    skipped_has_content: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    #: 被跳过的明细：(profile_id, title, field, 现有值, 源文本版本) —— 打印出来，别让"跳过"变成黑箱
    skipped_detail: list[tuple[int, str, str, Any, list[str]]] = field(default_factory=list)
    suspicious: list[tuple[int, str, list[str]]] = field(default_factory=list)
    no_raw: list[tuple[int, str]] = field(default_factory=list)
    samples: list[tuple[str, str, list[str]]] = field(default_factory=list)


async def _build_plan(session: AsyncSession, *, overwrite: bool) -> tuple[Plan, int]:
    """读库 + 算差异（**不写任何东西**）。返回 (计划, 岗位总数)。"""
    raw_rows = (
        await session.execute(
            select(JobRawData.title, JobRawData.description, JobRawData.requirements)
        )
    ).all()

    by_title: dict[str, list[tuple[str | None, str | None]]] = {}
    for title, description, requirements in raw_rows:
        by_title.setdefault(title, []).append((description, requirements))

    profiles = (await session.execute(select(JobProfile).order_by(JobProfile.id))).scalars().all()

    plan = Plan()
    for profile in profiles:
        sources = by_title.get(profile.title)
        if not sources:
            plan.no_raw.append((profile.id, profile.title))
            continue

        # 同名 raw 可能多行 → 取并集（保序去重），避免只认第一行漏掉内容
        merged: dict[str, list[str]] = {}
        for description, requirements in sources:
            for field_name, items in extract_career_fields(description, requirements).items():
                bucket = merged.setdefault(field_name, [])
                for item in items:
                    if item not in bucket:
                        bucket.append(item)

        for field_name in FIELDS:
            items = merged.get(field_name)
            if not items:
                continue

            plan.expected[field_name] += 1

            if looks_suspicious(items, field_name):
                plan.suspicious.append((profile.id, field_name, items))
                continue

            current = getattr(profile, field_name)
            if current == items:
                continue  # 已经是源文本版本，没什么可做
            if not overwrite and not _is_empty(current):
                plan.skipped_has_content[field_name] += 1
                plan.skipped_detail.append(
                    (profile.id, profile.title, field_name, current, items)
                )
                continue

            plan.changes.append(
                Change(
                    profile_id=profile.id,
                    title=profile.title,
                    field_name=field_name,
                    old=current,
                    new=items,
                )
            )
            if len(plan.samples) < 6:
                plan.samples.append((profile.title, field_name, items))

    return plan, len(profiles)


def _print_report(plan: Plan, total: int, *, applied: bool, overwrite: bool) -> None:
    mode = "APPLY（已写入）" if applied else "DRY-RUN（未写库）"
    print(f"\n===== 职业字段回填报告 [{mode}] =====", flush=True)
    print(f"岗位总数 = {total}；模式 = {'覆盖已有值' if overwrite else '只填空'}", flush=True)
    print("", flush=True)
    print(f"{'字段（源标签）':<34}{'可解析':>8}{'已有内容跳过':>14}{'本次改动':>10}", flush=True)
    print("-" * 68, flush=True)
    for field_name in FIELDS:
        count = sum(1 for c in plan.changes if c.field_name == field_name)
        label = f"{field_name}（{FIELD_LABELS[field_name]}）"
        print(
            f"{label:<30}{plan.expected[field_name]:>10}"
            f"{plan.skipped_has_content[field_name]:>14}{count:>10}",
            flush=True,
        )
    print("-" * 68, flush=True)
    print(f"本次改动合计 = {len(plan.changes)} 处", flush=True)

    if plan.samples:
        print("\n----- 解析样例（前几个）-----", flush=True)
        for title, field_name, items in plan.samples:
            print(f"  {title} · {field_name} → {items}", flush=True)

    if plan.suspicious:
        print(f"\n⚠️ 可疑解析（已跳过，不写库）{len(plan.suspicious)} 处：", flush=True)
        for profile_id, field_name, items in plan.suspicious[:5]:
            print(f"  profile {profile_id} · {field_name} → {items}", flush=True)

    if plan.skipped_detail:
        print(
            f"\n----- 「只填空」保留的旧值 {len(plan.skipped_detail)} 处"
            f"（与源文本版本不同；要改成源文本版本请加 --overwrite）-----",
            flush=True,
        )
        for profile_id, title, field_name, current, source_version in plan.skipped_detail[:12]:
            print(f"  profile {profile_id} · {title} · {field_name}", flush=True)
            print(f"      现有   = {current}", flush=True)
            print(f"      源文本 = {source_version}", flush=True)

    if plan.no_raw:
        print(f"\n⚠️ 找不到同名 raw 行的岗位 {len(plan.no_raw)} 条（无法回填）：", flush=True)
        for profile_id, title in plan.no_raw[:10]:
            print(f"  {profile_id} · {title}", flush=True)


def _write_backup(plan: Plan, backup_dir: Path) -> Path:
    resolved = backup_dir.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(
            f"[拒绝] 备份目录不能位于仓库内：{resolved}\n"
            f"       （仓库根 = {REPO_ROOT}）"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    csv_path = resolved / "career_fields_changes.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["profile_id", "title", "field", "old_value", "new_value"])
        for change in plan.changes:
            writer.writerow(
                [
                    change.profile_id,
                    change.title,
                    change.field_name,
                    "" if change.old is None else str(change.old),
                    " | ".join(change.new),
                ]
            )
    return csv_path


async def _apply(session: AsyncSession, plan: Plan) -> None:
    for change in plan.changes:
        profile = await session.get(JobProfile, change.profile_id)
        if profile is None:  # pragma: no cover - 计划与写入之间被删，属并发异常
            raise SystemExit(f"[中止] 岗位 {change.profile_id} 在回填过程中消失")
        setattr(profile, change.field_name, change.new)
    await session.flush()


async def _self_check(session: AsyncSession, plan: Plan) -> list[str]:
    """事务内自检：每条"能解析出内容"的字段都必须真的落上去了。返回失败说明列表。"""
    problems: list[str] = []
    total = (await session.execute(select(func.count()).select_from(JobProfile))).scalar() or 0
    print("\n----- 事务内自检 -----", flush=True)
    print(f"  岗位总数 = {total}", flush=True)

    for field_name in FIELDS:
        filled = (
            await session.execute(
                select(func.count())
                .select_from(JobProfile)
                .where(JobProfile.__table__.c[field_name].isnot(None))
            )
        ).scalar() or 0
        # JSON null 在 SQL 层不是 NULL，所以再数一次"非 JSON null 且非空容器"
        rows = (
            await session.execute(select(JobProfile.__table__.c[field_name]))
        ).scalars().all()
        real = sum(1 for value in rows if not _is_empty(value))
        print(
            f"  {field_name} 有内容 = {real}（可解析 {plan.expected[field_name]}）",
            flush=True,
        )
        if real < plan.expected[field_name]:
            problems.append(
                f"{field_name} 有内容 {real} < 可解析 {plan.expected[field_name]}"
            )
        if filled != real:
            problems.append(
                f"{field_name} 存在 JSON null 与 SQL NULL 混用（SQL 非空 {filled} / 实际有内容 {real}）"
            )
    return problems


async def _run(args: argparse.Namespace) -> int:
    backup_dir = (
        Path(args.backup_dir)
        if args.backup_dir
        else Path(tempfile.gettempdir()) / f"sjv-backfill-{datetime.now():%Y%m%d-%H%M%S}"
    )

    async with async_session_factory() as session:
        plan, total = await _build_plan(session, overwrite=args.overwrite)
        _print_report(plan, total, applied=False, overwrite=args.overwrite)

        if not args.apply:
            print("\n[提示] 这是 dry-run。确认无误后加 --apply 执行（会先备份到仓库外）。", flush=True)
            return 0

        if not plan.changes and not args.overwrite:
            print("\n[OK] 没有需要回填的字段（幂等：目标都已有内容）。", flush=True)
            return 0

        backup_path = _write_backup(plan, backup_dir)
        print(f"\n[OK] 备份（本次改动的旧值/新值）已写入: {backup_path}", flush=True)

        await _apply(session, plan)
        problems = await _self_check(session, plan)
        if problems:
            await session.rollback()
            print("\n[FAIL] 自检不通过，已回滚，未写任何数据：", flush=True)
            for problem in problems:
                print(f"  - {problem}", flush=True)
            return 1

        await session.commit()
        print(f"\n[完成] 已回填 {len(plan.changes)} 处并提交。", flush=True)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 job_raw_data 确定性回填 岗位晋升/换岗方向/所需证书 到 job_profiles"
    )
    parser.add_argument("--apply", action="store_true", help="真的写库（默认只 dry-run）")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有非空值（默认只填空；以后重跑 portrait 后一般仍用默认）",
    )
    parser.add_argument("--backup-dir", help="备份目录（默认 %%TEMP%%/sjv-backfill-<ts>，不得在仓库内）")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
