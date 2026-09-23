from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.admin.auth import require_admin
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.report_record import ReportRecord
from app.domain.models.user import User
from app.domain.services import snapshot_markdown
from app.infrastructure.database import get_db
from app.schemas.admin import (
    AdminSnapshotDetail,
    AdminSnapshotListResponse,
    AdminSnapshotSummary,
    AdminSnapshotUpdate,
    DimensionWeightCreate,
    DimensionWeightListResponse,
    DimensionWeightResponse,
    DimensionWeightUpdate,
)

router = APIRouter()


# ── 画像快照（替代原「匹配结果」：匹配明细已不落表，改为看快照与匹配状态，D9）──


def _report_count_expr():
    """该快照的关联报告数（相关子查询，避免列表接口 N+1）。"""
    inner = aliased(ReportRecord)
    return (
        select(func.count())
        .select_from(inner)
        .where(inner.profile_snapshot_id == ProfileSnapshot.id)
        .scalar_subquery()
    )


async def _username_and_report_count(
    snapshot_id: int, user_id: int, db: AsyncSession
) -> tuple[str | None, int]:
    username = (
        await db.execute(select(User.username).where(User.id == user_id))
    ).scalar_one_or_none()
    report_count = (
        await db.execute(
            select(func.count())
            .select_from(ReportRecord)
            .where(ReportRecord.profile_snapshot_id == snapshot_id)
        )
    ).scalar() or 0
    return username, report_count


def _to_summary(row, username: str | None, report_count: int) -> AdminSnapshotSummary:
    """Row（列表，按列选取）与 ORM 对象（详情）都能用。"""
    return AdminSnapshotSummary(
        id=row.id,
        user_id=row.user_id,
        username=username,
        profile_id=row.profile_id,
        serial_no=row.serial_no,
        description=row.description,
        matched=row.matched_at is not None,
        matched_at=row.matched_at,
        created_at=row.created_at,
        six_dim_scores=row.six_dim_scores_json or {},
        report_count=report_count,
    )


def _to_detail(row, username: str | None, report_count: int) -> AdminSnapshotDetail:
    summary = _to_summary(row, username, report_count)
    embedding = getattr(row, "embedding", None)
    return AdminSnapshotDetail(
        **summary.model_dump(),
        five_layers=row.five_layers_json or {},
        form_raw=row.form_raw_json or {},
        embedding_dim=len(embedding) if embedding is not None else None,
    )


@router.get("/snapshots", response_model=AdminSnapshotListResponse)
async def list_snapshots(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    matched: bool | None = Query(None, description="true=已匹配 / false=待匹配"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """画像快照列表（含匹配状态）。

    只选取列表需要的列 —— 不加载 embedding 向量（1024 维 × 每行）。
    """
    columns = (
        ProfileSnapshot.id,
        ProfileSnapshot.user_id,
        ProfileSnapshot.profile_id,
        ProfileSnapshot.serial_no,
        ProfileSnapshot.description,
        ProfileSnapshot.matched_at,
        ProfileSnapshot.created_at,
        ProfileSnapshot.six_dim_scores_json,
        User.username,
        _report_count_expr().label("report_count"),
    )
    query = (
        select(*columns)
        .select_from(ProfileSnapshot)
        .outerjoin(User, User.id == ProfileSnapshot.user_id)
    )
    count_query = select(func.count()).select_from(ProfileSnapshot)

    if user_id is not None:
        query = query.where(ProfileSnapshot.user_id == user_id)
        count_query = count_query.where(ProfileSnapshot.user_id == user_id)
    if matched is not None:
        cond = (
            ProfileSnapshot.matched_at.isnot(None)
            if matched
            else ProfileSnapshot.matched_at.is_(None)
        )
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        await db.execute(query.order_by(ProfileSnapshot.id.desc()).offset(skip).limit(limit))
    ).all()

    return AdminSnapshotListResponse(
        total=total,
        items=[_to_summary(r, r.username, r.report_count or 0) for r in rows],
    )


@router.get("/snapshots/{snapshot_id}", response_model=AdminSnapshotDetail)
async def get_snapshot(
    snapshot_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """画像快照详情（五层画像 + 冻结的六维分数 + 原始表单）。"""
    snap = await db.get(ProfileSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")
    username, report_count = await _username_and_report_count(snapshot_id, snap.user_id, db)
    return _to_detail(snap, username, report_count)


@router.put("/snapshots/{snapshot_id}", response_model=AdminSnapshotDetail)
async def update_snapshot(
    snapshot_id: int,
    data: AdminSnapshotUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """修改快照备注与五层画像（P1-4）。

    ⚠️ 只改 `description` / `five_layers_json`；**不重算** embedding 与六维分数 ——
    向量仍是快照生成时那份，改完画像与向量会不一致（如需一致，后续加"重算向量"按钮）。
    """
    snap = await db.get(ProfileSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")

    changes = data.model_dump(exclude_unset=True)
    if changes.get("description") is not None:
        snap.description = changes["description"]
    if changes.get("five_layers") is not None:
        snap.five_layers_json = changes["five_layers"]

    await db.commit()
    await db.refresh(snap)

    username, report_count = await _username_and_report_count(snapshot_id, snap.user_id, db)
    return _to_detail(snap, username, report_count)


@router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot(
    snapshot_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除画像快照。

    ⚠️ `report_records.profile_snapshot_id` 是 **ON DELETE CASCADE** → 该快照下的报告记录
    会被数据库一并删除。这里先把它们的 Word 文件路径取出来，删完再做尽力清理
    （与 `admin/reports.py` 的删除语义一致；文件删不掉也不影响记录删除这一业务结果）。
    前端会先用 `report_count` 明确提示。
    """
    snap = await db.get(ProfileSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")

    word_paths = (
        await db.execute(
            select(ReportRecord.word_file_path).where(
                ReportRecord.profile_snapshot_id == snapshot_id,
                ReportRecord.word_file_path.isnot(None),
            )
        )
    ).scalars().all()

    await db.delete(snap)
    await db.flush()

    for path in word_paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


@router.get("/snapshots/{snapshot_id}/download")
async def download_snapshot(
    snapshot_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """下载快照 Markdown（五层画像 + 六维分数 + 原始表单附录）。

    鉴权走 Authorization 头（前端用 axios blob + 临时 <a> 触发下载，同 S5 报告下载）。
    文件名给两份：ASCII 兜底 + RFC 5987 中文名，避免各浏览器乱码。
    """
    snap = await db.get(ProfileSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")

    username, _ = await _username_and_report_count(snapshot_id, snap.user_id, db)
    content = snapshot_markdown.render(snap, username)

    ascii_name = f"snapshot_{snap.user_id}_{snap.serial_no}.md"
    utf8_name = quote(f"快照_{snap.user_id}_{snap.serial_no}.md")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'
            )
        },
    )


# ── Dimension Weights ───────────────────────────────────────────────────────


@router.get("/weights", response_model=DimensionWeightListResponse)
async def list_dimension_weights(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    job_category: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List dimension weights with optional filtering."""
    query = select(DimensionWeight)
    count_query = select(func.count()).select_from(DimensionWeight)

    if job_category:
        query = query.where(DimensionWeight.job_category == job_category)
        count_query = count_query.where(DimensionWeight.job_category == job_category)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(DimensionWeight.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return DimensionWeightListResponse(
        total=total,
        items=[DimensionWeightResponse.model_validate(i) for i in items],
    )


@router.get("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def get_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single dimension weight by ID."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")
    return weight


@router.post("/weights", response_model=DimensionWeightResponse, status_code=status.HTTP_201_CREATED)
async def create_dimension_weight(
    data: DimensionWeightCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new dimension weight."""
    existing = await db.execute(
        select(DimensionWeight).where(
            DimensionWeight.job_category == data.job_category,
            DimensionWeight.top_dimension == data.top_dimension,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Dimension weight for this category and dimension already exists",
        )

    weight = DimensionWeight(**data.model_dump())
    db.add(weight)
    await db.flush()
    await db.refresh(weight)
    return weight


@router.put("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def update_dimension_weight(
    weight_id: int,
    data: DimensionWeightUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    weight.weight = data.weight
    await db.flush()
    await db.refresh(weight)
    return weight


@router.delete("/weights/{weight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    await db.delete(weight)
    await db.flush()
