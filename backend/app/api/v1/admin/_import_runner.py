"""导入任务的后台执行器：接真实 6+1 阶段流水线 + 阶段级进度落库。

S7-3 范围（父计划 §4 / 子计划 §3）：
- 用 ``compile_import_pipeline().astream()`` 接真实流水线（原先造 100 条假数据已删）；
- 阶段 → 进度百分比（D-S7-5=A），**每阶段 commit**，让 ``/progress`` 与 SSE 看得见推进；
- 计数映射 ``total_input→total_rows``、``total_passed→success_count``、``total_rejected→error_count``；
- D 级被拒原因写入有界 ``errors``（条数与单条长度都截断，避免 JSONB 膨胀）；
- 任一异常 → **整单 failed**（D-S7-6=A），``errors`` 给出原因。

B2-2 追加：流水线末尾新增 ``persist`` 阶段（第 7 阶段）真正落库 ——
``job_raw_data`` + ``job_profiles``(+ ``companies``)，统计写进 ``data_import_jobs.stats.persist``。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dedup_keys import normalise_title
from app.core.job_agent.graphs.import_pipeline import compile_import_pipeline
from app.domain.models.import_job import (
    IMPORT_STATUS_AWAITING_CONFIRMATION,
    IMPORT_STATUS_COMPLETED,
    IMPORT_STATUS_FAILED,
    DataImportJob,
)
from app.infrastructure.database import async_session_factory

# D-S7-3=A：单次导入行数上限。流水线每行 3 次 LLM（质检/提取/画像），
# 不设上限时误点一次就可能烧掉大量额度。
# 2026-09-26：由硬编码 50 提升为配置项 `settings.import_max_rows`
# （env `IMPORT_MAX_ROWS` 可覆盖，默认 100）。此前注释写着"S7-5 会提升"但从未做，
# 结果用户 86 行的文件**只被读前 50 行**，36 行从未进入流水线。
IMPORT_MAX_ROWS = get_settings().import_max_rows

# D-S7-5=A：阶段 → 进度百分比。前端既有契约是
# ``progress_pct = processed_rows / total_rows``（子计划 §1.4 不改前端契约），
# 因此阶段进度按 ``total_rows`` 折算进 ``processed_rows``，而不是新增字段。
# B2-2：末尾多了一个真正落库的 persist 阶段，故 portrait 从 100 降到 92。
# B3-1（2026-09-27）：插入 link_enrich 阶段 → 8 个阶段重新分配百分比。
# **必须保持严格递增**：前端进度条只认"只增不减"，回退会被看成卡死。
STAGE_PROGRESS: dict[str, int] = {
    "load_data": 14,
    "clean_data": 28,
    "dedup": 40,
    "link_enrich": 50,
    "quality_judge": 60,
    "extract": 72,
    "portrait": 86,
    "persist": 100,
}

# ``errors`` 是 JSONB，必须设上限：D 级行可能成百上千。
MAX_ERROR_ENTRIES = 20
MAX_ERROR_TEXT = 200


async def run_import_job(
    job_id: int,
    file_path: Path | None,
    *,
    slice_dir: Path | None = None,
) -> None:
    """后台任务主体：定位文件 →（切片模式下取下一片）→ 跑流水线 → 落状态。

    ``file_path`` / ``slice_dir`` 由 API 层（``import_module``）解析后传入，
    这样本模块不反向依赖 API 层，避免循环导入。

    B3（2026-10-03）起支持**切片模式**：`job.stats["slices"]` 有清单时，每次只跑
    **一片**，跑完把状态置为 `awaiting_confirmation` 等人工确认；不带切片信息的
    老工单仍然整表处理（向后兼容）。
    """
    async with async_session_factory() as session:
        job = await session.get(DataImportJob, job_id)
        if job is None:
            logger.warning("Import job 不存在，跳过 | job_id={}", job_id)
            return

        slices_state = ((job.stats or {}).get("slices") or {}) if job.stats else {}
        slice_meta = _resolve_slice(slices_state, slice_dir)

        if slice_meta is not None and slice_meta is not False:
            k, item, target_path = slice_meta
            if not target_path.exists():
                await _fail(
                    session, job, f"第 {k} 片文件缺失：{target_path.name}（请重新上传该文件）"
                )
                return
            try:
                await _run_pipeline(session, job, target_path, slice_meta=(k, item, slices_state))
            except Exception as exc:  # noqa: BLE001 - 后台任务必须落终态，不能静默丢失
                logger.exception("Import job 失败 | job_id={} | slice={} | error={}", job_id, k, exc)
                await _fail(session, job, str(exc)[:MAX_ERROR_TEXT])
                return
            logger.info(
                "Import job 完成一片 | job_id={} | slice={} | status={} | total={} | passed={}",
                job_id,
                k,
                job.status,
                job.total_rows,
                job.success_count,
            )
            return

        if slice_meta is False:
            # 清单存在但已经没有下一片（正常不会走到：最后一片跑完就 completed）
            job.status = IMPORT_STATUS_COMPLETED
            await session.commit()
            return

        if file_path is None:
            await _fail(session, job, f"未找到上传文件：uploads/import/{job_id}_*")
            return

        try:
            await _run_pipeline(session, job, file_path)
        except Exception as exc:  # noqa: BLE001 - 后台任务必须落终态，不能静默丢失
            logger.exception("Import job 失败 | job_id={} | error={}", job_id, exc)
            await _fail(session, job, str(exc)[:MAX_ERROR_TEXT])
            return

        logger.info(
            "Import job 完成 | job_id={} | total={} | passed={} | rejected={}",
            job_id,
            job.total_rows,
            job.success_count,
            job.error_count,
        )


async def _fail(session: AsyncSession, job: DataImportJob, reason: str) -> None:
    job.status = IMPORT_STATUS_FAILED
    job.errors = [*(job.errors or []), reason]
    job.error_count = max((job.total_rows or 0) - (job.processed_rows or 0), 0)
    await session.commit()


def _resolve_slice(
    slices_state: dict,
    slice_dir: Path | None,
) -> tuple[int, dict, Path] | bool | None:
    """决定本次要跑哪一片。

    Returns:
        - ``None``：没有切片清单 → 整表模式（老工单/小表）；
        - ``False``：有清单但已无下一片（全部跑完）；
        - ``(k, item, path)``：要跑第 k 片。
    """
    if not slices_state or not slices_state.get("slice_count"):
        return None
    if slice_dir is None:
        return None

    next_k = int(slices_state.get("next") or 1)
    items = {int(s["k"]): s for s in (slices_state.get("slices") or [])}
    item = items.get(next_k)
    if item is None:
        return False
    return next_k, item, Path(slice_dir) / str(item["file"])


async def _run_pipeline(
    session: AsyncSession,
    job: DataImportJob,
    file_path: Path,
    *,
    slice_meta: tuple[int, dict, dict] | None = None,
) -> None:
    """逐阶段消费流水线，每阶段落库一次进度。

    ``slice_meta`` = ``(片序号, 清单里的该片条目, 整个 slices 状态)``，非空时是
    **切片模式**：本片跑完后把状态停在 `awaiting_confirmation` 等人工确认，
    并把本片计数累加进 `stats.slices.cumulative`。
    """
    graph = compile_import_pipeline()
    payload = {
        "file_path": str(file_path),
        "sheet_name": 0,
        # D-S7-3 的行数上限只在**整表模式**下兜底；切片模式下片大小本身就是成本闸门，
        # 再套一层 nrows 会把尾片二次截断（旧实现 524 行只读前 100 行就是这么来的）。
        "nrows": None if slice_meta else IMPORT_MAX_ROWS,
    }

    state: dict = {}
    async for chunk in graph.astream(payload, stream_mode="updates"):
        for node, update in (chunk or {}).items():
            if node not in STAGE_PROGRESS:
                continue
            state.update(update or {})

            # 节点自报失败（如 load_data 读不动文件）必须立刻中断整单，
            # 否则流水线会拿着空数据一路跑完并报 completed（S7-3 实测缺陷）。
            failure = state.get("error_message") or (
                "流水线中止" if state.get("status") == "failed" else None
            )
            if failure:
                raise RuntimeError(str(failure))

            _apply_stage(job, node, state, slice_meta=slice_meta)
            # 每阶段 commit（而不是最后一次性写）：轮询与 SSE 才看得到进度推进，
            # 进程中断时也已留下最后一个完成阶段的进度。
            await session.commit()

    slice_input = int(state.get("total_input") or 0)
    passed = int(state.get("total_passed") or 0)
    rejected = int(state.get("total_rejected") or 0)
    # 本片真正落库成功的行涉及哪些岗位（`title_key`）。**必须经 `_finish_slice` 跨片累积**：
    # 阶段 8 只重算"本次导入碰到的岗位"，而"本次"是**所有片**的并集。
    # 只在最后一片现算会漏掉前几片的岗位 —— 实测 3 片样本里第 1 片的岗位从未被聚合，
    # 于是它永远只有"逐行 upsert"的画像，没有综合卡/薪资统计（B4 的全部价值都在聚合里）。
    touched = _touched_titles(state.get("passed_rows"))

    if slice_meta is None:
        # 整表模式：processed_rows 归位到 total_rows（=100%），计数取流水线累计值。
        job.total_rows = slice_input or job.total_rows or 0
        job.processed_rows = job.total_rows
        job.success_count = passed
        job.error_count = rejected
        job.status = IMPORT_STATUS_COMPLETED
        finished = True
    else:
        finished = _finish_slice(
            job, slice_meta, slice_input, passed, rejected, touched_titles=touched
        )
    await session.commit()

    if finished:
        # ── 阶段 8（B4-c，2026-10-03）：聚合成分等级的岗位画像 ──────────────────
        # **只在最后一片之后跑**：一个岗位组会跨片，只有全部片落完才看得到完整的一组。
        # 注意状态此刻已经是 `completed`（原始数据确实完整入库了）；聚合结果写进
        # `stats.aggregate`，失败只追加一条 error 而**不把已完成的导入改成失败** ——
        # 聚合是幂等且可单独重跑的（`scripts/rerun_aggregate.py`）。
        #
        # ⚠️ `stats.aggregate` 是**聚合跑完才写**的（见 `_run_aggregation`）：调用方
        # （含 `scripts/acceptance_import_pipeline.py`）看到 `completed` **不等于**
        # 聚合已完成 —— 聚合是 `completed` 之后的收尾，真实 87 组要几分钟。
        titles = touched if slice_meta is None else set(job.stats["slices"].get("touched_titles") or [])
        await _run_aggregation(session, job, titles)


def _touched_titles(rows: list[dict] | None) -> set[str]:
    """本次真正落库成功的行涉及哪些 `title_key`。

    只重算这些岗位（而不是整表所有岗位）：用户可能反复导入不同的小表，
    每次都把 87 个组全部重烧一遍（≈174 次 LLM）没有意义。
    """
    out: set[str] = set()
    for row in rows or []:
        title = str((row or {}).get("title") or "").strip()
        if title:
            out.add(normalise_title(title))
    return out


async def _run_aggregation(
    session: AsyncSession, job: DataImportJob, titles: set[str]
) -> None:
    """跑阶段 8 并把统计写进 `stats.aggregate`（失败不拖垮"导入已完成"）。

    ``titles`` = 本次导入**真正落库**的 `title_key` 集合。空集合 = 本次没有任何行入库
    （例如整片被质检判 D）→ **不跑聚合**。这里**不能**把空集合改写成 `None`：
    `aggregate_roles(titles=None)` 的语义是"重算全库所有岗位"，实测全库 87 组 ≈ 174 次
    LLM —— 一次"什么都没导进来"的操作会白烧一整轮额度，而结果与现状完全相同。
    """
    from app.domain.services.job_aggregate_service import aggregate_roles

    if not get_settings().import_aggregate_enabled:
        job.stats = {
            **(job.stats or {}),
            "aggregate": {"skipped": True, "reason": "IMPORT_AGGREGATE_ENABLED=false"},
        }
        await session.commit()
        return

    if not titles:
        job.stats = {
            **(job.stats or {}),
            "aggregate": {"skipped": True, "reason": "本次导入没有新落库的岗位"},
        }
        await session.commit()
        return

    try:
        stats = await aggregate_roles(session, titles=titles)
    except Exception as exc:  # noqa: BLE001 - 聚合失败不该让已入库的数据看起来"没导进来"
        logger.exception("聚合阶段失败 | job_id={} | error={}", job.id, exc)
        job.stats = {
            **(job.stats or {}),
            "aggregate": {"ok": 0, "failed": -1, "error": f"{type(exc).__name__}: {exc}"[:200]},
        }
        job.errors = [
            *(job.errors or []),
            f"聚合阶段失败：{str(exc)[:150]}（原始数据已入库，可重跑聚合）",
        ]
        await session.commit()
        return

    job.stats = {**(job.stats or {}), "aggregate": stats}
    if stats.get("failed"):
        job.errors = [
            *(job.errors or []),
            f"聚合：{stats['failed']}/{stats['groups']} 组失败（可重跑聚合，原始数据不受影响）",
        ]
    await session.commit()


def _finish_slice(
    job: DataImportJob,
    slice_meta: tuple[int, dict, dict],
    slice_input: int,
    passed: int,
    rejected: int,
    *,
    touched_titles: set[str] | None = None,
) -> bool:
    """一片跑完：累加计数、推进 `next`、决定停在哪。返回**是否已全部跑完**。

    - 还有下一片 → `awaiting_confirmation`（**等人工确认**，用户 2026-10-03 拍板）；
    - 已是最后一片 → `completed`。

    `processed_rows` 始终是**累计已处理行数**（不是本片行数）：前端进度条契约是
    `processed_rows / total_rows`，跨片必须单调递增、不能回退。

    `touched_titles` 会**跨片累积**到 `stats.slices.touched_titles` ——
    阶段 8 的聚合只重算这些岗位（否则每次导入都把所有岗位重烧一遍 LLM）。
    """
    k, _item, slices_state = slice_meta
    total_slices = int(slices_state.get("slice_count") or 0)
    manifest_total = int(slices_state.get("total_rows") or 0)

    cumulative = dict(slices_state.get("cumulative") or {"rows": 0, "passed": 0, "rejected": 0})
    cumulative["rows"] = int(cumulative.get("rows") or 0) + slice_input
    cumulative["passed"] = int(cumulative.get("passed") or 0) + passed
    cumulative["rejected"] = int(cumulative.get("rejected") or 0) + rejected

    done = sorted({*(slices_state.get("done") or []), k})
    next_k = k + 1
    finished = next_k > total_slices
    touched = sorted({*(slices_state.get("touched_titles") or []), *(touched_titles or set())})

    job.stats = {
        **(job.stats or {}),
        "slices": {
            **slices_state,
            "done": done,
            "next": next_k,
            "cumulative": cumulative,
            "touched_titles": touched,
            "state": IMPORT_STATUS_COMPLETED if finished else IMPORT_STATUS_AWAITING_CONFIRMATION,
        },
    }
    job.total_rows = manifest_total
    job.success_count = cumulative["passed"]
    job.error_count = cumulative["rejected"]
    job.processed_rows = manifest_total if finished else cumulative["rows"]
    job.status = IMPORT_STATUS_COMPLETED if finished else IMPORT_STATUS_AWAITING_CONFIRMATION
    return finished


def _apply_stage(
    job: DataImportJob,
    node: str,
    state: dict,
    *,
    slice_meta: tuple[int, dict, dict] | None = None,
) -> None:
    """把「刚跑完某个节点」这件事折算成 job 上的可观测字段。

    注意：流水线自身的 ``status``（loaded/cleaned/...）**不写进 job.status**，
    前端契约只认 pending/processing/awaiting_confirmation/completed/failed。
    """
    pct = STAGE_PROGRESS[node]

    if slice_meta is None:
        total = int(state.get("total_input") or 0)
        if total > 0:
            job.total_rows = total
            job.processed_rows = min(int(round(total * pct / 100)), total)
    else:
        # 切片模式：进度 = 「已完成片的累计行数」+ 本片按阶段折算的进度。
        _k, _item, slices_state = slice_meta
        slice_input = int(state.get("total_input") or 0)
        base = int((slices_state.get("cumulative") or {}).get("rows") or 0)
        job.total_rows = int(slices_state.get("total_rows") or job.total_rows or 0)
        if slice_input > 0 and job.total_rows > 0:
            job.processed_rows = min(
                base + int(round(slice_input * pct / 100)), job.total_rows
            )

    if node in ("quality_judge", "extract", "portrait"):
        passed = int(state.get("total_passed") or 0)
        rejected = int(state.get("total_rejected") or 0)
        if slice_meta is not None:
            # 切片模式：本片计数要叠上**已完成片**的累计值，否则每开新片计数会掉回 0，
            # 前端看到的"成功 N 条"会随切片来回跳。
            cumulative = slice_meta[2].get("cumulative") or {}
            passed += int(cumulative.get("passed") or 0)
            rejected += int(cumulative.get("rejected") or 0)
        job.success_count = passed
        job.error_count = rejected

    if node == "quality_judge":
        job.errors = _summarize_rejections(
            state.get("rejected_rows") or [],
            state.get("quality_results") or [],
        )

    if node == "load_data":
        # A/B 层（2026-09-26）：把"这张表是什么体裁、有哪些字段"写进 stats，
        # 前端导入详情可见 —— 判 D 太多时管理员能立刻看出是体裁/列名问题。
        schema = state.get("schema_profile") or {}
        if schema:
            job.stats = {**(job.stats or {}), "schema": schema}

    if node == "dedup":
        # B2（2026-10-03）：逐级删除数 + 告警落库。
        # 事故复盘：旧实现把 100 行并成 1 行（删 99%）、4366 行并成 1 行，
        # 工单却报 `completed`/`success_count=1`，**管理员完全看不到异常**。
        # 现在既写结构化 stats，也把告警放进 `errors`（前端"失败原因预览卡"直接可见）。
        dedup_stats = state.get("dedup_stats") or {}
        if dedup_stats:
            job.stats = {**(job.stats or {}), "dedup": dedup_stats}
            alerts = list(dedup_stats.get("alerts") or [])
            if alerts:
                job.errors = [*(job.errors or []), *[f"去重告警：{a}" for a in alerts]]

    if node == "persist":
        # B2-2：落库统计可见（前端导入详情可直接展示"入库 N 条 / 新建 vs 更新"）
        persist_stats = state.get("persist_stats") or {}
        job.stats = {**(job.stats or {}), "persist": persist_stats}

    if node == "link_enrich":
        # B3-1：链接富化统计（发现多少链接、抓了几个、命中 JSON-LD 几个、
        # 补了哪些字段、有没有撞预算上限）。开关关闭时也会写一条 enabled=false，
        # 让"为什么这次没富化"在导入详情里自解释。
        enrich_stats = state.get("link_enrich_stats") or {}
        if enrich_stats:
            job.stats = {**(job.stats or {}), "link_enrich": enrich_stats}

    if node == "portrait":
        # 2026-09-27：画像成功/失败计数落库。原先 portrait 失败静默返回默认值，
        # stats 只显示 persist.failed=0 → "#853 的 82 行里 73 行画像是默认值"却
        # 看起来完全成功（§20.1）。现在导入详情能直接看到 portrait.failed。
        portrait_stats = state.get("portrait_stats") or {}
        if portrait_stats:
            job.stats = {**(job.stats or {}), "portrait": portrait_stats}


def _summarize_rejections(rejected_rows: list[dict], quality_results: list[dict]) -> list[str]:
    """D 级行 → 可读原因列表（条数与单条长度都有上限）。

    质检节点按 ``deduped_rows`` 顺序逐行调用 ``quality_judge``，
    因此 ``quality_results`` 中 grade=="D" 的顺序与 ``rejected_rows`` 一一对应。
    """
    reasons: list[str] = []
    d_results = [r for r in quality_results if isinstance(r, dict) and r.get("grade") == "D"]

    for row, result in zip(rejected_rows[:MAX_ERROR_ENTRIES], d_results):
        title = str(row.get("title") or row.get("岗位名称") or "未知岗位")
        score = result.get("score")
        text = f"{title}：D 级（{score} 分）" if score is not None else f"{title}：D 级"
        summary = str(result.get("summary") or "").strip()
        if summary:
            text = f"{text} {summary}"
        reasons.append(text[:MAX_ERROR_TEXT])

    remaining = len(rejected_rows) - MAX_ERROR_ENTRIES
    if remaining > 0:
        reasons.append(f"...另有 {remaining} 条 D 级未逐条列出")

    return reasons
