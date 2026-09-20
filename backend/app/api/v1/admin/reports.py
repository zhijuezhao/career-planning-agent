from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.admin.auth import require_admin
from app.domain.models.report_record import ReportRecord
from app.domain.models.user import User
from app.domain.services.report_service import ensure_report_word, record_version
from app.infrastructure.database import get_db
from app.schemas.admin import (
    AdminReportDetail,
    AdminReportListResponse,
    AdminReportSummary,
)

router = APIRouter()

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _version_expr():
    """version = 该用户 id <= 本记录 id 的记录条数（与 report_service.record_version 同定义）。

    用相关子查询在【一条 SQL】里算出，避免列表接口 N+1；且不依赖分页/过滤后的行集。
    注意：不能用 row_number() OVER (...) —— 一旦带过滤条件，窗口会只在过滤后的子集上编号。
    """
    inner = aliased(ReportRecord)
    return (
        select(func.count())
        .select_from(inner)
        .where(inner.user_id == ReportRecord.user_id, inner.id <= ReportRecord.id)
        .scalar_subquery()
    )


async def _get_record(report_id: int, db: AsyncSession) -> ReportRecord:
    rec = await db.get(ReportRecord, report_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="报告记录不存在")
    return rec


@router.get("", response_model=AdminReportListResponse)
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    keyword: str | None = Query(None, description="按描述模糊搜索"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """报告记录列表（report_records；原 CareerReport 表已随数据模型重构删除）。"""
    query = select(ReportRecord, _version_expr().label("version"))
    count_query = select(func.count()).select_from(ReportRecord)

    if user_id is not None:
        query = query.where(ReportRecord.user_id == user_id)
        count_query = count_query.where(ReportRecord.user_id == user_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(ReportRecord.description.like(like))
        count_query = count_query.where(ReportRecord.description.like(like))

    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        await db.execute(query.order_by(ReportRecord.id.desc()).offset(skip).limit(limit))
    ).all()

    return AdminReportListResponse(
        total=total,
        items=[
            AdminReportSummary(
                id=rec.id,
                user_id=rec.user_id,
                profile_snapshot_id=rec.profile_snapshot_id,
                serial_no=rec.serial_no,
                description=rec.description,
                version=version,
                created_at=rec.created_at,
            )
            for rec, version in rows
        ],
    )


@router.get("/{report_id}", response_model=AdminReportDetail)
async def get_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """报告记录详情（含完整 report_text）。"""
    rec = await _get_record(report_id, db)
    return AdminReportDetail(
        id=rec.id,
        user_id=rec.user_id,
        profile_snapshot_id=rec.profile_snapshot_id,
        serial_no=rec.serial_no,
        description=rec.description,
        version=await record_version(rec.id, rec.user_id, db),
        created_at=rec.created_at,
        report_text=rec.report_text,
        word_file_path=rec.word_file_path,
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """下载报告 Word：惰性生成（无文件时现场生成并落库）后返回。

    鉴权走 Authorization 头（管理端前端已改为带 blob 请求；原 ?token= 方式不再支持）。
    """
    rec = await _get_record(report_id, db)
    path = await ensure_report_word(rec, db)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="报告文件缺失")
    version = await record_version(rec.id, rec.user_id, db)
    filename = f"生涯发展报告_v{version}_{rec.serial_no}.docx"
    return FileResponse(path=path, filename=filename, media_type=DOCX_MEDIA_TYPE)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除报告记录（顺带尽力删除已生成的 Word 文件）。"""
    rec = await _get_record(report_id, db)
    word_path = rec.word_file_path
    await db.delete(rec)
    await db.flush()
    if word_path:
        try:
            Path(word_path).unlink(missing_ok=True)
        except OSError:
            # 文件删除失败不影响删除记录这一业务结果
            pass
