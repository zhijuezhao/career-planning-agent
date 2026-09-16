from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.report_record import ReportRecord
from app.domain.models.user import User
from app.domain.services.report_service import (
    create_report_record,
    ensure_report_word,
    record_version,
)
from app.infrastructure.database import get_db
from app.schemas.reports import ReportGenerateRequest, ReportRecordResponse, ReportRecordSummary

router = APIRouter()

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _get_owned_record(rid: int, user_id: int, db: AsyncSession) -> ReportRecord:
    """取用户自己的报告记录；不存在/不属于该用户 → 404。"""
    rec = (
        await db.execute(
            select(ReportRecord).where(
                ReportRecord.id == rid,
                ReportRecord.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="报告记录不存在")
    return rec


@router.post("/generate", response_model=ReportRecordResponse)
async def generate_report(
    body: ReportGenerateRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ReportRecordResponse:
    """生成报告记录：冻结快照 + 恰好 3 项匹配结果 → 6 模块文本入库（惰性 Word）。"""
    snap = (
        await db.execute(
            select(ProfileSnapshot).where(
                ProfileSnapshot.id == body.profile_snapshot_id,
                ProfileSnapshot.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise HTTPException(status_code=404, detail="快照不存在")

    if len(body.matching_results) != 3:
        raise HTTPException(
            status_code=422,
            detail="matching_results 必须恰为 3 项 {job_profile_id, match_score}",
        )

    rec = await create_report_record(user.id, snap, body.matching_results, db)
    return ReportRecordResponse(
        id=rec.id,
        user_id=rec.user_id,
        profile_snapshot_id=rec.profile_snapshot_id,
        serial_no=rec.serial_no,
        description=rec.description,
        version=await record_version(rec.id, user.id, db),
        created_at=rec.created_at,
        report_text=rec.report_text,
        word_file_path=rec.word_file_path,
    )


@router.get("/records", response_model=list[ReportRecordSummary])
async def list_records(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ReportRecordSummary]:
    """当前用户的报告记录列表（无 report_text，带 version）。"""
    rows = (
        await db.execute(
            select(ReportRecord)
            .where(ReportRecord.user_id == user.id)
            .order_by(ReportRecord.created_at.desc())
        )
    ).scalars().all()
    # 同事务内读取：created_at 单调 → id 单调，version = count(id <= this)
    version_by_id = {(rec.id): idx + 1 for idx, rec in enumerate(sorted(rows, key=lambda r: r.id))}
    return [
        ReportRecordSummary(
            id=rec.id,
            user_id=rec.user_id,
            profile_snapshot_id=rec.profile_snapshot_id,
            serial_no=rec.serial_no,
            description=rec.description,
            version=version_by_id[rec.id],
            created_at=rec.created_at,
        )
        for rec in rows
    ]


@router.get("/records/{rid}", response_model=ReportRecordResponse)
async def record_detail(
    rid: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ReportRecordResponse:
    """报告记录详情：完整 report_text + 惰性 Word 路径。"""
    rec = await _get_owned_record(rid, user.id, db)
    return ReportRecordResponse(
        id=rec.id,
        user_id=rec.user_id,
        profile_snapshot_id=rec.profile_snapshot_id,
        serial_no=rec.serial_no,
        description=rec.description,
        version=await record_version(rec.id, user.id, db),
        created_at=rec.created_at,
        report_text=rec.report_text,
        word_file_path=rec.word_file_path,
    )


@router.get("/records/{rid}/download")
async def record_download(
    rid: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """下载报告 Word：惰性生成（无文件时现场生成并落库）后返回。"""
    rec = await _get_owned_record(rid, user.id, db)
    path = await ensure_report_word(rec, db)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="报告文件缺失")
    filename = f"生涯发展报告_v{await record_version(rec.id, user.id, db)}_{rec.serial_no}.docx"
    return FileResponse(path=path, filename=filename, media_type=DOCX_MEDIA_TYPE)