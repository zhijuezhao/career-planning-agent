from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.report import CareerReport, ChatSession, JobMatch
from app.domain.models.resume import Resume
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.infrastructure.security import hash_password
from app.schemas.admin import (
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserStats,
    AdminUserUpdate,
)

router = APIRouter()


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    role: str | None = None,
    status: int | None = Query(None, ge=0, le=1),
    keyword: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with optional filtering."""
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if status is not None:
        query = query.where(User.status == status)
        count_query = count_query.where(User.status == status)
    if keyword:
        like = f"%{keyword}%"
        query = query.where((User.username.like(like)) | (User.email.like(like)))
        count_query = count_query.where((User.username.like(like)) | (User.email.like(like)))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(User.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return AdminUserListResponse(
        total=total,
        items=[AdminUserResponse.model_validate(u) for u in users],
    )


@router.get("/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single user by ID."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/stats", response_model=AdminUserStats)
async def get_user_stats(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get usage statistics for a specific user."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    resume_count = (await db.execute(
        select(func.count()).select_from(Resume).where(Resume.user_id == user_id)
    )).scalar() or 0

    match_count = (await db.execute(
        select(func.count()).select_from(JobMatch).where(JobMatch.user_id == user_id)
    )).scalar() or 0

    report_count = (await db.execute(
        select(func.count()).select_from(CareerReport).where(CareerReport.user_id == user_id)
    )).scalar() or 0

    chat_session_count = (await db.execute(
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)
    )).scalar() or 0

    return AdminUserStats(
        user_id=user.id,
        username=user.username,
        resume_count=resume_count,
        match_count=match_count,
        report_count=report_count,
        chat_session_count=chat_session_count,
    )


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user profile."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    if "password" in update_data and update_data["password"]:
        update_data["password_hash"] = hash_password(update_data.pop("password"))

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=AdminUserResponse)
async def reset_password(
    user_id: int,
    new_password: str = Query(..., min_length=6, max_length=128),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(new_password)
    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.flush()
