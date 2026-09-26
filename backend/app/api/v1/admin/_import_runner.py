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
from app.core.job_agent.graphs.import_pipeline import compile_import_pipeline
from app.domain.models.import_job import DataImportJob
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
STAGE_PROGRESS: dict[str, int] = {
    "load_data": 16,
    "clean_data": 33,
    "dedup": 50,
    "quality_judge": 66,
    "extract": 83,
    "portrait": 92,
    "persist": 100,
}

# ``errors`` 是 JSONB，必须设上限：D 级行可能成百上千。
MAX_ERROR_ENTRIES = 20
MAX_ERROR_TEXT = 200


async def run_import_job(job_id: int, file_path: Path | None) -> None:
    """后台任务主体：定位文件 → 跑流水线 → 落终态。

    ``file_path`` 由 API 层（``import_module._find_upload_file``）解析后传入，
    这样本模块不反向依赖 API 层，避免循环导入。
    """
    async with async_session_factory() as session:
        job = await session.get(DataImportJob, job_id)
        if job is None:
            logger.warning("Import job 不存在，跳过 | job_id={}", job_id)
            return

        if file_path is None:
            job.status = "failed"
            job.errors = [f"未找到上传文件：uploads/import/{job_id}_*"]
            job.error_count = 0
            await session.commit()
            return

        try:
            await _run_pipeline(session, job, file_path)
        except Exception as exc:  # noqa: BLE001 - 后台任务必须落终态，不能静默丢失
            logger.exception("Import job 失败 | job_id={} | error={}", job_id, exc)
            job.status = "failed"
            job.errors = [str(exc)[:MAX_ERROR_TEXT]]
            job.error_count = max(job.total_rows - job.processed_rows, 0)
            await session.commit()
            return

        logger.info(
            "Import job 完成 | job_id={} | total={} | passed={} | rejected={}",
            job_id,
            job.total_rows,
            job.success_count,
            job.error_count,
        )


async def _run_pipeline(session: AsyncSession, job: DataImportJob, file_path: Path) -> None:
    """逐阶段消费流水线，每阶段落库一次进度。"""
    graph = compile_import_pipeline()
    payload = {
        "file_path": str(file_path),
        "sheet_name": 0,
        "nrows": IMPORT_MAX_ROWS,  # D-S7-3：行数上限在读取阶段生效
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

            _apply_stage(job, node, state)
            # 每阶段 commit（而不是最后一次性写）：轮询与 SSE 才看得到进度推进，
            # 进程中断时也已留下最后一个完成阶段的进度。
            await session.commit()

    # 终态：processed_rows 归位到 total_rows（=100%），计数取流水线累计值。
    job.total_rows = int(state.get("total_input") or job.total_rows or 0)
    job.processed_rows = job.total_rows
    job.success_count = int(state.get("total_passed") or 0)
    job.error_count = int(state.get("total_rejected") or 0)
    job.status = "completed"
    await session.commit()


def _apply_stage(job: DataImportJob, node: str, state: dict) -> None:
    """把「刚跑完某个节点」这件事折算成 job 上的可观测字段。

    注意：流水线自身的 ``status``（loaded/cleaned/...）**不写进 job.status**，
    前端契约只认 pending/processing/completed/failed（子计划 §1.4）。
    """
    pct = STAGE_PROGRESS[node]

    total = int(state.get("total_input") or 0)
    if total > 0:
        job.total_rows = total
        job.processed_rows = min(int(round(total * pct / 100)), total)

    if node in ("quality_judge", "extract", "portrait"):
        job.success_count = int(state.get("total_passed") or 0)
        job.error_count = int(state.get("total_rejected") or 0)

    if node == "quality_judge":
        job.errors = _summarize_rejections(
            state.get("rejected_rows") or [],
            state.get("quality_results") or [],
        )

    if node == "persist":
        # B2-2：落库统计可见（前端导入详情可直接展示"入库 N 条 / 新建 vs 更新"）
        persist_stats = state.get("persist_stats") or {}
        job.stats = {**(job.stats or {}), "persist": persist_stats}


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
