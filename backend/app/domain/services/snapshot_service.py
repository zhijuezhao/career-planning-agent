from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.embeddings import get_embeddings
from app.core.resume_agent.embedding_text import build_portrait_text
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.student_profile import StudentProfile

logger = logging.getLogger(__name__)

# Vector(1024) NOT NULL 且无 server default：pgvector 拒绝 0 维向量，
# embedding 不可用时一律用零向量占位（快照创建绝不因 embedding 失败）。
_ZERO_EMBEDDING = [0.0] * 1024


async def create_profile_snapshot(user_id: int, db: AsyncSession) -> ProfileSnapshot:
    """为 user 创建（或去重回用）ProfileSnapshot，返回已提交实例。

    R-3/4-2: 先确保 student_profiles 行存在（profile_id 非空 FK 依赖）。
    R-4-3: 快照 = 纯冻结——five_layers 取 form["five_layers"]，
           六维分数取 form["dimension_scoring"]（Task 3 解析-only 不落候选行）。
    R-4-1: embedding 调用受保护；任何异常或空文本 → 零向量占位。
    """
    form_row = (
        await db.execute(
            select(StudentProfile).where(StudentProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    if form_row is None:
        form_row = StudentProfile(user_id=user_id)
        db.add(form_row)
        await db.flush()

    form_raw = dict(form_row.resume_form) if form_row.resume_form else {}

    # 去重：user 最新快照的 form_raw_json == 当前 form → 直接返回既有（不变更）
    existing = (
        await db.execute(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.user_id == user_id)
            .order_by(ProfileSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.form_raw_json == form_raw:
        return existing

    # 组装（所有数据来自 form_raw —— 上传返回的 five_layers/dimension_scoring 已随表单回填）
    five_layers = form_raw.get("five_layers") or {}
    dims = form_raw.get("dimension_scoring") or {}

    text = build_portrait_text(five_layers)
    if text.strip():
        try:
            vec = await get_embeddings().aembed_query(text)
            if not vec:
                vec = _ZERO_EMBEDDING
        except Exception:  # embedding 服务故障 → 零向量，绝不 fail 快照
            logger.exception("embedding failed, using zero vector | user_id=%s", user_id)
            vec = _ZERO_EMBEDDING
    else:
        vec = _ZERO_EMBEDDING

    snap = ProfileSnapshot(
        user_id=user_id,
        profile_id=user_id,  # profile_id=user_id（1:1，见 Interfaces 注）
        form_raw_json=form_raw,
        five_layers_json=five_layers,
        six_dim_scores_json=dims,
        embedding=vec,
        serial_no=uuid.uuid4(),
        description="",
        matched_at=None,
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap