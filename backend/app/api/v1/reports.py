from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.report import CareerReport
from app.domain.models.user import User
from app.domain.services.report_service import (
    create_report,
    get_report_by_id,
    get_user_reports,
)
from app.infrastructure.database import get_db
from app.schemas.reports import (
    ReportGenerateRequest,
    ReportListResponse,
    ReportResponse,
)

router = APIRouter()


@router.post("/generate", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def generate_report(
    request: ReportGenerateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """生成生涯发展报告（含 Word 导出）。"""
    try:
        report = await create_report(
            user_id=current_user.id,
            profile_id=request.profile_id,
            target_job=request.target_job,
            session=db,
        )
        return report
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"报告生成失败: {exc}") from exc


@router.get("", response_model=ReportListResponse)
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的报告列表。"""
    count_stmt = select(func.count()).select_from(CareerReport).where(CareerReport.user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = await get_user_reports(current_user.id, db, skip=skip, limit=limit)
    return ReportListResponse(
        total=total,
        items=[ReportResponse.model_validate(r) for r in items],
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report_detail(
    report_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个报告详情。"""
    report = await get_report_by_id(report_id, db)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    if report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此报告")
    return report


@router.get("/{report_id}/download")
async def download_report(
    report_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """下载报告 Word 文件。"""
    report = await get_report_by_id(report_id, db)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    if report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此报告")
    if not report.word_file_path:
        raise HTTPException(status_code=404, detail="报告文件不存在")

    import os
    if not os.path.exists(report.word_file_path):
        raise HTTPException(status_code=404, detail="报告文件已删除")

    filename = os.path.basename(report.word_file_path)
    return FileResponse(
        path=report.word_file_path,
        filename=f"生涯发展报告_v{report.version}_{filename}",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
