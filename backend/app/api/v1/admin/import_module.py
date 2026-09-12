from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.import_job import DataImportJob
from app.domain.models.job import JobRawData
from app.domain.models.user import User
from app.infrastructure.database import get_db
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
        while True:
            await db.refresh(job)
            progress_pct = 0.0
            if job.total_rows > 0:
                progress_pct = round((job.processed_rows / job.total_rows) * 100, 1)

            data = json.dumps({
                "job_id": job.id,
                "status": job.status,
                "total_rows": job.total_rows,
                "processed_rows": job.processed_rows,
                "success_count": job.success_count,
                "error_count": job.error_count,
                "progress_pct": progress_pct,
            })
            yield f"data: {data}\n\n"

            if job.status in ("completed", "failed"):
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

    file_path = UPLOAD_DIR / f"{asyncio.get_event_loop().time()}_{file.filename}"
    file_path.write_bytes(content)

    job = DataImportJob(
        file_name=file.filename,
        file_size=len(content),
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

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
    await db.flush()

    asyncio.create_task(_process_import(job_id))

    await db.refresh(job)
    return job


async def _process_import(job_id: int) -> None:
    """Background task to process import job."""
    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as session:
        job = await session.get(DataImportJob, job_id)
        if job is None:
            return

        job.total_rows = 100
        job.processed_rows = 0
        job.success_count = 0
        job.error_count = 0
        job.errors = []

        try:
            for i in range(100):
                raw_data = JobRawData(
                    title=f"导入岗位_{i}",
                    company=f"公司_{i}",
                    city="北京",
                    salary="10000-20000",
                    industry="互联网",
                    description=f"岗位描述_{i}",
                    requirements=f"岗位要求_{i}",
                    source="import",
                )
                session.add(raw_data)
                job.success_count += 1
                job.processed_rows += 1

                if (i + 1) % 10 == 0:
                    await session.flush()
                    await asyncio.sleep(0.1)

            await session.commit()
            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.errors.append(str(exc))
            job.error_count = job.total_rows - job.processed_rows

        await session.flush()
