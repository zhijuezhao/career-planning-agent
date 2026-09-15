from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.config import get_settings
from app.core.resume_agent.parse_graph import parse_resume_only
from app.domain.models.resume import Resume
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.resume import ResumeDetailResponse, ResumeStatusResponse, ResumeUploadResponse
from app.utils.file_storage import save_upload_file

router = APIRouter()


@router.post("/upload", status_code=202, response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    settings_obj = get_settings()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()

    if len(file_bytes) > settings_obj.max_upload_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings_obj.max_upload_size_mb}MB",
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
    try:
        result = await parse_resume_only(file_path, resume.id)
    except Exception as exc:
        await db.rollback()
        resume.status = "failed"
        resume.error_message = str(exc)
        await db.commit()
        logger.error("Resume parse failed | id={} | error={}", resume.id, exc)
        raise HTTPException(status_code=500, detail="Resume parsing failed")

    resume.parsed_data = result["parsed_resume"] if result.get("parsed_resume") else {}
    resume.status = "parsed"
    await db.commit()
    return ResumeUploadResponse(
        resume_id=resume.id,
        status="parsed",
        five_layers=result.get("five_layers"),
        dimension_scoring=result.get("dimension_scoring"),
    )


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
        error_message=resume.error_message,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
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