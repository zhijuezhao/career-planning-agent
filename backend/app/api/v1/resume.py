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
from app.utils.file_storage import compute_file_hash, save_upload_file

router = APIRouter()


def _parse_response_from_stored(resume: Resume) -> ResumeUploadResponse:
    """把库里**已解析**的简历还原成 `/upload` 的响应体（**不再跑一次 LLM**）。

    `five_layers` 没有落库（库里只有 `parsed_data` = LLM 的原始解析结果），但它是
    `parsed_data` 经 `map_to_five_layers()` **纯本地规则**推导出来的 —— 所以这里现场重算一遍，
    零 LLM 调用、结果与首次上传完全一致。
    """
    from app.core.resume_agent.schemas import ParsedResume
    from app.core.resume_agent.tools.five_layer_mapper import map_to_five_layers

    parsed = resume.parsed_data or {}
    five_layers = None
    try:
        five_layers = map_to_five_layers(ParsedResume.model_validate(parsed))
    except Exception:  # noqa: BLE001 - 存量数据形状不合法时降级：只回评分，不炸接口
        logger.warning("复用已解析简历时五层映射失败 | resume_id={}", resume.id)
    return ResumeUploadResponse(
        resume_id=resume.id,
        status=resume.status,
        five_layers=five_layers,
        dimension_scoring=parsed.get("dimension_scoring"),
    )


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

    # 同一份 PDF 重复上传 → **复用已解析结果**，不再解析第二次。
    #
    # 为什么必须有（2026-10-04 实测事故）：本接口是**同步解析**（LLM 跑完才返回），
    # 1 页 PDF 要 35–40 秒；而前端 `student/src/api/request.ts` 的 axios 超时是 **30 秒** ——
    # 客户端先 abort，后端却照常跑完并落库，用户看到"解析失败，请重试"就又传一次。
    # 实测同一份简历（`content_hash` 相同）被完整解析了 **3 次**：3 条重复记录 + 3 次 LLM 花费。
    # 有了这一步，重试变成零成本（前端超时兜底也就能给出"仍会出结果"的准确提示）。
    content_hash = compute_file_hash(file_bytes)
    existing = (
        await db.execute(
            select(Resume)
            .where(
                Resume.user_id == current_user.id,
                Resume.content_hash == content_hash,
                Resume.status == "parsed",
            )
            .order_by(desc(Resume.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "重复上传同一份简历，复用已解析结果 | user_id={} | resume_id={} | hash={}",
            current_user.id,
            existing.id,
            content_hash[:12],
        )
        return _parse_response_from_stored(existing)

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
