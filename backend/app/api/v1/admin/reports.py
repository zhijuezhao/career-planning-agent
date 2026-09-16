from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
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
    raise HTTPException(status_code=501, detail="职业报告管理依赖已删的 CareerReport 表，暂不提供")


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single career report by ID."""
    raise HTTPException(status_code=501, detail="职业报告管理依赖已删的 CareerReport 表，暂不提供")


@router.get("/{report_id}/download")
async def download_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download the Word document of a career report."""
    raise HTTPException(status_code=501, detail="职业报告管理依赖已删的 CareerReport 表，暂不提供")


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a career report."""
    raise HTTPException(status_code=501, detail="职业报告管理依赖已删的 CareerReport 表，暂不提供")