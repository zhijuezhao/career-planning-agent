from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.import_job import DataImportJob
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
            })
            yield f"data: {data}\n\n"

            if current.status in ("completed", "failed"):
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
        status="pending",
    )
    db.add(job)
    await db.flush()  # 同事务内取回 id；落盘抛错会随请求回滚，不留孤儿行

    safe_name = Path(file.filename or "").name or "unnamed"  # 去掉目录成分，防路径穿越
    file_path = UPLOAD_DIR / f"{job.id}_{safe_name}"
    file_path.write_bytes(content)

    return job


@router.post("/{job_id}/process", response_model=ImportJobResponse)
async def process_import_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start processing an import job."""
    job = await db.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")

    if job.status not in ("pending", "failed"):
        raise HTTPException(status_code=400, detail=f"Cannot process job in {job.status} status")

    job.status = "processing"
    job.processed_rows = 0
    job.success_count = 0
    job.error_count = 0
    job.errors = []
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
    """后台任务：定位上传文件 → 统计真实行数 → 落终态。

    S7-1 范围仅「文件定位 + 真实行数 + 状态机」：**不跑 6 阶段流水线、不写库**，
    因此不会产生任何 job_raw_data / job_profiles 记录（原实现造 100 条假岗位已删除）。
    """
    from app.core.job_agent.tools.data_loader import load_excel_data

    async with async_session_factory() as session:
        job = await session.get(DataImportJob, job_id)
        if job is None:
            return

        file_path = _find_upload_file(job_id)
        if file_path is None:
            job.status = "failed"
            job.errors = [f"未找到上传文件：uploads/import/{job_id}_*"]
            job.error_count = 0
            await session.commit()
            return

        try:
            result = await load_excel_data.ainvoke({"file_path": str(file_path)})
            if result.get("error"):
                raise RuntimeError(str(result["error"]))

            total = int(result.get("total") or 0)
            job.total_rows = total
            job.processed_rows = total
            # S7-1 的 success_count 语义 = 成功解析（读取）的行数；
            # S7-3/S7-4 接入流水线与落库后会改写为「通过质检 / 实际落库」条数。
            job.success_count = total
            job.error_count = 0
            job.errors = []
            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.errors = [str(exc)]
            job.error_count = max(job.total_rows - job.processed_rows, 0)

        await session.commit()
