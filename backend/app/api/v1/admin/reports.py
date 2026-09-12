from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.report import CareerReport
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import ReportListResponse, ReportResponse

router = APIRouter()


@router.get("", response_model=ReportListResponse)
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List career reports with optional filtering."""
    query = select(CareerReport)
    count_query = select(func.count()).select_from(CareerReport)

    if user_id is not None:
        query = query.where(CareerReport.user_id == user_id)
        count_query = count_query.where(CareerReport.user_id == user_id)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(CareerReport.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return ReportListResponse(
        total=total,
        items=[ReportResponse.model_validate(i) for i in items],
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single career report by ID."""
    report = await db.get(CareerReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/{report_id}/download")
async def download_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download the Word document of a career report."""
    report = await db.get(CareerReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not report.word_file_path:
        raise HTTPException(status_code=404, detail="No Word document available for this report")

    return FileResponse(
        path=report.word_file_path,
        filename=f"career_report_{report_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a career report."""
    report = await db.get(CareerReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    await db.delete(report)
    await db.flush()
