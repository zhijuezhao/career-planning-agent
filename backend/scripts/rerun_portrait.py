"""重跑岗位画像（`portrait_builder`），**只写画像列**。

为什么需要它（主计划 §20.1）
--------------------------
`#853` 导入时 `job_portrait` 未绑定 → 回落 `default` → 当时绑的是 longcat（≈25s/次），
而 `LLM_REQUEST_TIMEOUT=60` → **82 行里约 73 行画像失败并静默兜底**（五维全 3、
outlook「成熟」、summary 空）。失败原因现在已修（`portrait_builder` 重试一次 +
返回 `portrait_ok`，导入 `stats.portrait` 可查），但**已经写坏的数据要靠这个脚本重跑补上**。

⚠️ **岗位信息 vs 岗位画像**（用户 2026-09-27 要求）
--------------------------------------------------
本脚本只经 `job_persist_service.apply_job_portrait()` 写库，它按
`field_groups.PORTRAIT_FIELDS` 白名单行事（`requirement_intensity` / `outlook` / `summary`）。
脚本**跑完会自检**：所有「岗位信息」列（`title`/`hard_skills`/`career_path`/
`transition_paths`/`certificates`/…）必须**一字未变**，否则回滚。
`portrait_builder` 返回的 `career_paths` / `transition_roles` 从此**不再**写进岗位信息列。

⚠️ 会花 token，且不幂等
-----------------------
每行一次模型调用（重试最多 2 次）；画像本身由模型产出，**重跑结果不会与上次完全相同**。
所以：默认 dry-run（**不调模型**），必须 `--apply` 才真跑；用 `--limit` / `--title` 先小样试。

用法（**必须在后端容器里跑**：脚本 import `app.*`，宿主 `.env` 含 docker 专用键会报错）::

    docker exec -e PYTHONPATH=/app/backend -w /app/backend career_backend \\
        python scripts/rerun_portrait.py                       # dry-run：只看目标与现状
    docker exec -e PYTHONPATH=/app/backend -w /app/backend career_backend \\
        python scripts/rerun_portrait.py --apply --limit 3     # 先跑 3 条试水
    docker exec -e PYTHONPATH=/app/backend -w /app/backend career_backend \\
        python scripts/rerun_portrait.py --apply               # 全量
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.job_agent.field_groups import JOB_INFO_FIELDS
from app.core.job_agent.tools.portrait_builder import portrait_builder
from app.domain.models.job import JobProfile, JobRawData
from app.domain.services.job_persist_service import apply_job_portrait
from app.infrastructure.database import async_session_factory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 画像输入用到的 job_raw_data 列（必须与 `import_pipeline.node_portrait` 的口径一致：
#: 那边喂的是「清洗后的行」，落库后等价物就是这些列）
PORTRAIT_INPUT_KEYS: tuple[str, ...] = (
    "title",
    "company",
    "city",
    "salary",
    "industry",
    "description",
    "requirements",
)

#: 每跑多少条打印一次进度（82 条 × 慢模型可能几十分钟，得能看见在动）
PROGRESS_EVERY = 5


@dataclass
class Target:
    profile: JobProfile
    job_data: str


@dataclass
class RunReport:
    total: int = 0
    ok: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    #: 重跑前"看起来就是默认值"的条数（用于说明这次重跑到底修了多少）
    default_like_before: int = 0
    #: 重跑后仍有区分度的条数（五维不是同一个分）
    differentiated_after: int = 0


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (list, dict, str)) and len(value) == 0)


def _five_dim_scores(value: Any) -> list[int]:
    if not isinstance(value, dict):
        return []
    scores: list[int] = []
    for dim in value.values():
        if isinstance(dim, dict) and isinstance(dim.get("score"), int):
            scores.append(dim["score"])
    return scores


def _looks_default(profile: JobProfile) -> bool:
    """是不是"看起来就是兜底默认值"：五维同分 + summary 为空。"""
    scores = _five_dim_scores(profile.requirement_intensity)
    same_score = len(scores) >= 2 and len(set(scores)) == 1
    return same_score and not (profile.summary or "").strip()


def _portrait_input(profile: JobProfile, raws: list[JobRawData]) -> str | None:
    """按 `import_pipeline.node_portrait` 的口径重建画像输入（JSON 字符串）。

    ⚠️ 同名 raw 可能**多行**（实测 `前端开发工程师` 等同名 2 条，其中一条
    `description` 恰好是空的）→ 必须取**内容最全**的那条。否则喂给模型的输入只剩
    `{"title": ..., "city": ...}`，重跑出来的画像等于瞎编（dry-run 的输入预览就是
    为了让人一眼看出这种事）。
    """
    if not raws:
        return None
    raw = max(raws, key=lambda r: len(r.description or "") + len(r.requirements or ""))
    payload: dict[str, Any] = {"title": profile.title}
    for key in PORTRAIT_INPUT_KEYS:
        value = getattr(raw, key, None)
        if value not in (None, ""):
            payload[key] = value
    if len(payload) == 1:
        return None
    return json.dumps(payload, ensure_ascii=False)


async def _load_targets(
    session: AsyncSession, *, titles: list[str] | None, limit: int | None
) -> list[Target]:
    raws = (await session.execute(select(JobRawData))).scalars().all()
    by_title: dict[str, list[JobRawData]] = {}
    for raw in raws:
        by_title.setdefault(raw.title, []).append(raw)

    stmt = select(JobProfile).order_by(JobProfile.id)
    profiles = (await session.execute(stmt)).scalars().all()

    targets: list[Target] = []
    for profile in profiles:
        if titles and profile.title not in titles:
            continue
        job_data = _portrait_input(profile, by_title.get(profile.title, []))
        if job_data is None:
            continue
        targets.append(Target(profile=profile, job_data=job_data))
    if limit is not None:
        targets = targets[:limit]
    return targets


def _snapshot_facts(targets: list[Target]) -> dict[int, tuple]:
    """给每个目标的**岗位信息列**拍快照（跑完用来证明一字未变）。"""
    return {
        t.profile.id: tuple(
            json.dumps(getattr(t.profile, column), ensure_ascii=False, sort_keys=True, default=str)
            for column in sorted(JOB_INFO_FIELDS)
        )
        for t in targets
    }


def _facts_diff(before: dict[int, tuple], targets: list[Target]) -> list[str]:
    problems: list[str] = []
    for target in targets:
        after = tuple(
            json.dumps(
                getattr(target.profile, column), ensure_ascii=False, sort_keys=True, default=str
            )
            for column in sorted(JOB_INFO_FIELDS)
        )
        if before[target.profile.id] != after:
            changed = [
                column
                for column, old, new in zip(
                    sorted(JOB_INFO_FIELDS), before[target.profile.id], after, strict=True
                )
                if old != new
            ]
            problems.append(f"profile {target.profile.id} · {target.profile.title}：{changed}")
    return problems


def _write_backup(rows: list[tuple], backup_dir: Path) -> Path:
    resolved = backup_dir.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(f"[拒绝] 备份目录不能位于仓库内：{resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / "portrait_before_after.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["profile_id", "title", "field", "before", "after"])
        writer.writerows(rows)
    return path


async def _run(args: argparse.Namespace) -> int:
    backup_dir = (
        Path(args.backup_dir)
        if args.backup_dir
        else Path(tempfile.gettempdir()) / f"sjv-portrait-{datetime.now():%Y%m%d-%H%M%S}"
    )

    async with async_session_factory() as session:
        targets = await _load_targets(session, titles=args.title or None, limit=args.limit)
        if not targets:
            print("[OK] 没有匹配到任何岗位（检查 --title / 库里是否有数据）", flush=True)
            return 0

        report = RunReport(total=len(targets))
        report.default_like_before = sum(1 for t in targets if _looks_default(t.profile))

        print(f"\n===== 重跑岗位画像 [{'APPLY' if args.apply else 'DRY-RUN'}] =====", flush=True)
        print(f"目标条数 = {report.total}", flush=True)
        print(
            f"其中「看起来就是默认值」= {report.default_like_before}"
            f"（五维同分 + summary 空 → 大概率是 §20.1 那次静默兜底）",
            flush=True,
        )
        print("\n----- 输入样例（与导入时同一口径）-----", flush=True)
        for target in targets[:2]:
            preview = target.job_data[:220].replace("\n", " ")
            print(f"  {target.profile.title} → {preview}…", flush=True)

        if not args.apply:
            print(
                "\n[提示] 这是 dry-run（**没有调用模型、没有花 token**）。"
                "\n       真跑请加 --apply；建议先 --limit 3 小样试水。",
                flush=True,
            )
            return 0

        facts_before = _snapshot_facts(targets)
        before_rows: dict[int, dict[str, Any]] = {
            t.profile.id: {
                column: getattr(t.profile, column)
                for column in ("requirement_intensity", "outlook", "summary")
            }
            for t in targets
        }

        for index, target in enumerate(targets, start=1):
            result = await portrait_builder.ainvoke({"job_data": target.job_data})
            if result.get("portrait_ok", True):
                report.ok += 1
            else:
                report.failed += 1
                if len(report.failures) < 10:
                    report.failures.append(
                        (target.profile.title, str(result.get("portrait_error")))
                    )
            # 只写画像列（白名单）；岗位信息列一个都不碰
            apply_job_portrait(target.profile, result)
            if index % PROGRESS_EVERY == 0 or index == len(targets):
                print(
                    f"  …进度 {index}/{len(targets)}（ok={report.ok} 失败={report.failed}）",
                    flush=True,
                )

        # ── 自检 1：岗位信息列必须一字未变（用户 2026-09-27 的核心要求）──────────
        problems = _facts_diff(facts_before, targets)
        print("\n----- 事务内自检 -----", flush=True)
        print(
            f"  岗位信息列（{len(JOB_INFO_FIELDS)} 列）保持不变的条数 = "
            f"{len(targets) - len(problems)} / {len(targets)}",
            flush=True,
        )
        report.differentiated_after = sum(
            1 for t in targets if len(set(_five_dim_scores(t.profile.requirement_intensity))) > 1
        )
        print(
            f"  重跑后「五维有区分度」= {report.differentiated_after} / {len(targets)}"
            f"（重跑前默认值 {report.default_like_before} 条）",
            flush=True,
        )
        print(f"  画像成功 = {report.ok}，失败（落了默认值）= {report.failed}", flush=True)

        if problems:
            await session.rollback()
            print("\n[FAIL] 有岗位信息列被改动，已回滚：", flush=True)
            for problem in problems[:10]:
                print(f"  - {problem}", flush=True)
            return 1

        backup_rows: list[tuple] = []
        for target in targets:
            for column, before in before_rows[target.profile.id].items():
                after = getattr(target.profile, column)
                if before != after:
                    backup_rows.append(
                        (
                            target.profile.id,
                            target.profile.title,
                            column,
                            json.dumps(before, ensure_ascii=False, default=str),
                            json.dumps(after, ensure_ascii=False, default=str),
                        )
                    )
        path = _write_backup(backup_rows, backup_dir)
        print(f"\n[OK] 画像改动前/后已备份: {path}（{len(backup_rows)} 行）", flush=True)

        if report.failures:
            print("\n⚠️ 失败样例：", flush=True)
            for title, error in report.failures:
                print(f"  {title}：{error}", flush=True)

        await session.commit()
        print(f"\n[完成] 已重跑 {report.total} 条并提交（画像列）。", flush=True)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="重跑岗位画像（只写画像列，不碰岗位信息）")
    parser.add_argument("--apply", action="store_true", help="真的调用模型并写库（默认 dry-run）")
    parser.add_argument("--title", action="append", help="只重跑这些岗位名（可重复）")
    parser.add_argument("--limit", type=int, help="最多重跑多少条（先小样试水）")
    parser.add_argument("--backup-dir", help="备份目录（默认 %%TEMP%%/sjv-portrait-<ts>，不得在仓库内）")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
