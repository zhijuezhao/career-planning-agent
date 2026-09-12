from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.config import get_settings
from app.domain.models.report import CareerReport
from app.domain.models.resume import Resume
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.resume import ReportResponse, ResumeDetailResponse, ResumeStatusResponse
from app.utils.file_storage import save_upload_file

router = APIRouter()


async def _run_resume_pipeline(resume_id: int, file_path: str, user_id: int) -> None:
    from app.core.resume_agent.graph import compile_resume_graph
    from app.domain.services.resume_service import update_resume_status
    from app.infrastructure.database import async_session_factory

    try:
        graph = compile_resume_graph()
        await graph.ainvoke({
            "resume_id": resume_id,
            "user_id": user_id,
            "file_path": file_path,
            "status": "uploaded",
        })
    except Exception as exc:
        logger.error("Resume pipeline failed | id={} | error={}", resume_id, exc)
        try:
            async with async_session_factory() as session:
                await update_resume_status(session, resume_id, "failed", error_message=str(exc))
                await session.commit()
        except Exception:
            logger.exception("Failed to update resume status to failed | id={}", resume_id)


@router.post("/upload", status_code=202)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()

    if len(file_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.max_upload_size_mb}MB",
        )

    if not file_bytes[:5].startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    file_path, content_hash = save_upload_file(file_bytes, current_user.id, file.filename)

    resume = Resume(
        user_id=current_user.id,
        file_name=file.filename,
        file_path=file_path,
        file_size=len(file_bytes),
        content_hash=content_hash,
        status="uploaded",
    )
    db.add(resume)
    await db.flush()
    await db.refresh(resume)
    await db.commit()

    if background_tasks is not None:
        background_tasks.add_task(_run_resume_pipeline, resume.id, file_path, current_user.id)

    return {"resume_id": resume.id, "status": "uploaded"}


@router.get("/latest", response_model=ResumeStatusResponse)
async def get_latest_resume(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(desc(Resume.created_at))
        .limit(1)
    )
    result = await db.execute(stmt)
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="No resume found")
    return ResumeStatusResponse(
        resume_id=resume.id,
        status=resume.status,
        error_message=resume.error_message,
        profile_id=resume.profile_id,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


@router.get("/{resume_id}", response_model=ResumeDetailResponse)
async def get_resume_detail(
    resume_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    resume = await db.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeDetailResponse(
        resume_id=resume.id,
        file_name=resume.file_name,
        status=resume.status,
        page_count=resume.page_count,
        parsed_data=resume.parsed_data,
        profile_id=resume.profile_id,
        error_message=resume.error_message,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


@router.get("/{resume_id}/report", response_model=ReportResponse)
async def get_resume_report(
    resume_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    resume = await db.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.profile_id is None:
        raise HTTPException(status_code=404, detail="No profile linked to this resume")

    stmt = (
        select(CareerReport)
        .where(CareerReport.profile_id == resume.profile_id)
        .order_by(desc(CareerReport.created_at))
        .limit(1)
    )
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportResponse(
        report_id=report.id,
        profile_id=report.profile_id,
        target_job=report.target_job,
        report_content=report.report_content,
        version=report.version,
        created_at=report.created_at,
    )


@router.get("/{resume_id}/radar")
async def get_resume_radar(
    resume_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    from app.core.resume_agent.visualization import build_radar_option

    resume = await db.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    dimension_scoring = (resume.parsed_data or {}).get("dimension_scoring")
    return build_radar_option(dimension_scoring)
