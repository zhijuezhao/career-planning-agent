from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin import _import_runner
from app.api.v1.admin.auth import require_admin
from app.config import get_settings
from app.core.job_agent.slices import (
    SLICE_SUBDIR,
    manifest_file_name,
    sha256_file,
    write_slices,
)
from app.core.job_agent.tools.data_loader import read_raw_table
from app.domain.models.import_job import (
    IMPORT_PROCESSABLE_STATUSES,
    IMPORT_STATUS_AWAITING_CONFIRMATION,
    IMPORT_STATUS_FAILED,
    IMPORT_STATUS_PENDING,
    IMPORT_STATUS_PROCESSING,
    IMPORT_TERMINAL_STATUSES,
    DataImportJob,
)
from app.domain.models.user import User
from app.infrastructure.database import async_session_factory, get_db
from app.schemas.admin import (
    ImportJobListResponse,
    ImportJobResponse,
    ImportProgressResponse,
)

router = APIRouter()

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
UPLOAD_DIR = Path("uploads/import")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SSE_MAX_SECONDS = 900  # SSE 最长存活（防止客户端断连后无限占用连接）


def _find_upload_file(job_id: int) -> Path | None:
    """按 `<job_id>_*` 定位上传文件（S7-1 决策 D-S7-1=A：文件名即索引，无 schema 变更）。"""
    matches = sorted(UPLOAD_DIR.glob(f"{job_id}_*"))
    return matches[0] if matches else None


def _slice_batch_id(job_id: int) -> str:
    return f"job{job_id}"


def _slice_dir(job_id: int) -> Path:
    """切片目录：`uploads/import/slices/job<id>/`。

    放子目录的原因：`_find_upload_file()` 用 `<job_id>_*` 匹配原文件，
    子目录不会被它误匹配成一个"上传文件"。
    """
    return UPLOAD_DIR / SLICE_SUBDIR / _slice_batch_id(job_id)


def _schedule_process(job_id: int) -> None:
    """把后台处理挂到当前事件循环。

    单独抽出的原因：这是「状态已落库 → 才允许起任务」的接缝，
    测试用它断言调度发生的那一刻 DB 里已是 processing（反竞态）。
    """
    asyncio.create_task(_process_import(job_id))


@router.get("", response_model=ImportJobListResponse)
async def list_import_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List import jobs with optional filtering."""
    query = select(DataImportJob)
    count_query = select(func.count()).select_from(DataImportJob)

    if status_filter:
        query = query.where(DataImportJob.status == status_filter)
        count_query = count_query.where(DataImportJob.status == status_filter)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(DataImportJob.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return ImportJobListResponse(
        total=total,
        items=[ImportJobResponse.model_validate(i) for i in items],
    )


@router.get("/{job_id}", response_model=ImportJobResponse)
async def get_import_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single import job by ID."""
    job = await db.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


def _slice_progress(stats: dict | None) -> dict:
    """从 `stats.slices` 提取前端要的三个数（第 k/N 片 + 状态 + 警告）。"""
    slices = (stats or {}).get("slices") or {}
    if not slices:
        return {}
    return {
        "slice_total": slices.get("slice_count"),
        "slice_done": len(slices.get("done") or []),
        "slice_next": slices.get("next"),
        "slice_state": slices.get("state"),
        "slice_warning": slices.get("error") or slices.get("warning"),
    }


@router.get("/{job_id}/progress", response_model=ImportProgressResponse)
async def get_import_progress(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the progress of an import job."""
    job = await db.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")

    progress_pct = 0.0
    if job.total_rows > 0:
        progress_pct = round((job.processed_rows / job.total_rows) * 100, 1)

    return ImportProgressResponse(
        job_id=job.id,
        status=job.status,
        total_rows=job.total_rows,
        processed_rows=job.processed_rows,
        success_count=job.success_count,
        error_count=job.error_count,
        progress_pct=progress_pct,
        **_slice_progress(job.stats),
    )


@router.get("/{job_id}/stream")
async def stream_import_progress(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Stream import progress via SSE."""
    job = await db.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")

    async def event_generator():
        # S7-1：不再复用请求级 session（原写法长期占用一条连接且跨任务共享事务），
        # 改为每轮新开一个短 session 读取快照。
        deadline = time.monotonic() + SSE_MAX_SECONDS
        while True:
            async with async_session_factory() as session:
                current = await session.get(DataImportJob, job_id)
            if current is None:
                break

            progress_pct = 0.0
            if current.total_rows > 0:
                progress_pct = round((current.processed_rows / current.total_rows) * 100, 1)

            data = json.dumps({
                "job_id": current.id,
                "status": current.status,
                "total_rows": current.total_rows,
                "processed_rows": current.processed_rows,
                "success_count": current.success_count,
                "error_count": current.error_count,
                "progress_pct": progress_pct,
                **_slice_progress(current.stats),
            })
            yield f"data: {data}\n\n"

            if current.status in IMPORT_TERMINAL_STATUSES or current.status == IMPORT_STATUS_AWAITING_CONFIRMATION:
                # B3：`awaiting_confirmation` 也是「本轮到此为止」——
                # 停在这里让前端把"继续下一片"按钮亮出来，而不是一直挂着 SSE 等。
                break
            if time.monotonic() > deadline:
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/upload", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file for import."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # S7-1（D-S7-1=A）：先建 job 行拿到自增 id，再以 `<job_id>_<safe_name>` 落盘。
    # 文件名本身即索引，处理阶段用 `uploads/import/{job_id}_*` 定位，无需新增 file_path 列。
    job = DataImportJob(
        file_name=file.filename,
        file_size=len(content),
        status=IMPORT_STATUS_PENDING,
    )
    db.add(job)
    await db.flush()  # 同事务内取回 id；落盘抛错会随请求回滚，不留孤儿行

    safe_name = Path(file.filename or "").name or "unnamed"  # 去掉目录成分，防路径穿越
    file_path = UPLOAD_DIR / f"{job.id}_{safe_name}"
    file_path.write_bytes(content)

    # B3（2026-10-03）：上传即切片（用户要求"切成好几份、序列号 1、2、3…"）。
    # 在这里做的好处：① 预检信息（切几片/共多少行/哪列没认出来）能立刻返回；
    # ② 清单与每片 sha256/行指纹在**处理之前**就固定下来，后面每次处理都从磁盘重算校验，
    #    能证明"不丢行、不重行、没被改过"。
    slices_state = await asyncio.to_thread(_build_slices, job.id, file_path, safe_name)
    job.stats = {**(job.stats or {}), "slices": slices_state}

    return job


def _build_slices(job_id: int, file_path: Path, source_name: str) -> dict:
    """读原始表 → 切片 → 写清单；返回可直接塞进 `job.stats["slices"]` 的状态。

    同步实现（由 `asyncio.to_thread` 调用）：pandas 读写是阻塞的，不该占事件循环。
    """
    slice_size = get_settings().import_slice_size
    out_dir = _slice_dir(job_id)
    batch_id = _slice_batch_id(job_id)

    try:
        columns, rows = read_raw_table(str(file_path), sheet_name=0)
    except Exception as exc:  # noqa: BLE001 - 读不动要如实记下来，处理时会失败并说明原因
        return {
            "batch_id": batch_id,
            "total_rows": 0,
            "slice_size": slice_size,
            "slice_count": 0,
            "slices": [],
            "state": IMPORT_STATUS_FAILED,
            "next": 1,
            "done": [],
            "cumulative": {"rows": 0, "passed": 0, "rejected": 0},
            "error": f"读取失败：{type(exc).__name__}: {exc}",
        }

    if not rows:
        # 空表必须显式记下来：旧实现把「读到 0 行」当成功一路跑完并报 completed，
        # 用户看到"导入成功"却一条都没有（实测 1480/1481 两个工单）。
        return {
            "batch_id": batch_id,
            "total_rows": 0,
            "slice_size": slice_size,
            "slice_count": 0,
            "slices": [],
            "state": IMPORT_STATUS_PENDING,
            "next": 1,
            "done": [],
            "cumulative": {"rows": 0, "passed": 0, "rejected": 0},
            "warning": "该工作表没有任何数据行（可能是空表，或数据不在第一个工作表里）",
        }

    manifest = write_slices(
        rows,
        columns,
        out_dir=out_dir,
        batch_id=batch_id,
        slice_size=slice_size,
        source_name=source_name,
        source_sha256=sha256_file(file_path),
    )
    return {
        **manifest,
        "manifest_file": manifest_file_name(batch_id),
        "state": IMPORT_STATUS_PENDING,
        "next": 1,
        "done": [],
        "cumulative": {"rows": 0, "passed": 0, "rejected": 0},
    }


@router.post("/{job_id}/process", response_model=ImportJobResponse)
async def process_import_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """开始 / **继续下一片**处理一个导入工单。

    B3（2026-10-03）起这个接口也是「切片暂停闸门」的放行口：
    状态为 `awaiting_confirmation` 时再点一次就等于"确认，处理下一片"。
    """
    job = await db.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")

    if job.status not in IMPORT_PROCESSABLE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot process job in {job.status} status")

    slices_state = (job.stats or {}).get("slices") or {}
    if slices_state and not slices_state.get("slice_count"):
        # 空表/读取失败的工单：明确报错，不再"假成功"
        detail = slices_state.get("error") or slices_state.get("warning") or "该文件没有可处理的数据行"
        raise HTTPException(status_code=400, detail=detail)

    # ⚠️ 只在**第一片**重置计数。切片续跑时重置会把已完成的进度抹掉，
    # 而 `_finish_slice` 的累计值是从 `stats.slices.cumulative` 读的，两者必须一致。
    is_first_run = not slices_state or int(slices_state.get("next") or 1) <= 1
    if is_first_run:
        job.processed_rows = 0
        job.success_count = 0
        job.error_count = 0
        job.errors = []

    job.status = IMPORT_STATUS_PROCESSING
    # S7-1：必须【先 commit 再起任务】。后台任务开独立 session，未提交它就看不到
    # processing（原实现只 flush 就 create_task，存在竞态，任务结束还可能把状态覆盖回去）。
    await db.commit()
    # commit 后 refresh 取回库端生成列（updated_at 由 onupdate 生成，不取会在响应
    # 序列化时触发懒加载 → asyncpg 下 MissingGreenlet）。放在 create_task 之前，
    # 保证响应体稳定是 processing 快照，不随后台任务调度时间抖动。
    await db.refresh(job)

    _schedule_process(job_id)

    return job


async def _process_import(job_id: int) -> None:
    """后台任务入口（薄适配层）：定位上传文件后交给 runner 执行。

    S7-3 起真正的执行逻辑在 :mod:`app.api.v1.admin._import_runner`
    （6 阶段流水线、阶段级进度、计数映射、失败落库）。
    B3 起还要把**切片目录约定**翻译成一个 Path 传进去（切片模式下只跑下一片）。
    本函数只负责「把 API 层的上传目录约定翻译成 Path」。
    """
    await _import_runner.run_import_job(
        job_id, _find_upload_file(job_id), slice_dir=_slice_dir(job_id)
    )
