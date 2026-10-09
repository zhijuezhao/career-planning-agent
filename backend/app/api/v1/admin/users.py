from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.config import get_settings
from app.core.roles import USER_ROLE_ADMIN, UserRole
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.report import ChatMessage, ChatSession
from app.domain.models.report_record import ReportRecord
from app.domain.models.resume import Resume
from app.domain.models.student_profile import StudentProfile
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.infrastructure.security import hash_password
from app.schemas.admin import (
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserStats,
    AdminUserUpdate,
    ResetPasswordRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _remove_resume_files(user_id: int, paths: list[str]) -> int:
    """删除该用户简历的磁盘文件，返回实际删除数。

    必须**在 DB 提交成功之后**调用（见 `delete_user`）：磁盘删除不可回滚，
    顺序反过来就会出现「文件没了、库里还留着行」。

    安全约束：只允许删 `{upload_dir}/user_{user_id}/` **目录内**的文件。`file_path` 是
    历史/可被改写的值，做前缀校验可避免脏数据删到目录外的东西（越权删除）。

    删除失败只记 warning、不让接口失败：库里的行已经删干净，重试也没有意义。
    """
    if not paths:
        return 0

    base_dir = Path(get_settings().upload_dir)
    if not base_dir.is_absolute():
        # `save_upload_file` 写盘时用的是相对 cwd 的 settings.upload_dir，
        # 这里按同一基准还原成绝对路径，才能做前缀比较
        base_dir = Path.cwd() / base_dir
    allowed_dir = (base_dir / f"user_{user_id}").resolve()

    removed = 0
    for raw in paths:
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            resolved = candidate.resolve()
            if not resolved.is_relative_to(allowed_dir):
                logger.warning(
                    "skip resume file outside user dir | user=%s path=%s", user_id, raw
                )
                continue
            resolved.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning(
                "cannot remove resume file | user=%s path=%s error=%s", user_id, raw, exc
            )

    # 目录空了顺手删掉，避免磁盘上留一堆空 user_* 目录
    try:
        if allowed_dir.is_dir() and not any(allowed_dir.iterdir()):
            allowed_dir.rmdir()
    except OSError as exc:
        logger.warning(
            "cannot remove resume dir | user=%s dir=%s error=%s", user_id, allowed_dir, exc
        )
    return removed


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    role: UserRole | None = Query(None, description="按角色筛选（白名单外 422）"),
    status: int | None = Query(None, ge=0, le=1),
    keyword: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with optional filtering.

    B2-4 改造：
    - `role` 收白名单（`UserRole`）→ 非法角色 422，不再静默返回空列表；
    - `keyword` 除用户名/邮箱外，同时匹配手机号/QQ/微信（B2-4 的字段要能查得到，
      否则建了列也只能一页页翻）。
    """
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
        keyword_filter = or_(
            User.username.like(like),
            User.email.like(like),
            User.phone.like(like),
            User.qq.like(like),
            User.wechat.like(like),
        )
        query = query.where(keyword_filter)
        count_query = count_query.where(keyword_filter)

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
    """Get usage statistics for a specific user.

    B2-4 补 `snapshot_count` / `profile_count`：删除用户时数据库会 CASCADE 掉画像快照与
    画像，管理端确认框需要如实列出"还会删掉什么"。
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    resume_count = (await db.execute(
        select(func.count()).select_from(Resume).where(Resume.user_id == user_id)
    )).scalar() or 0

    chat_session_count = (await db.execute(
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)
    )).scalar() or 0

    # 已匹配快照数（原 JobMatch 表已删除，S4 改为真值）
    match_count = (await db.execute(
        select(func.count())
        .select_from(ProfileSnapshot)
        .where(
            ProfileSnapshot.user_id == user_id,
            ProfileSnapshot.matched_at.isnot(None),
        )
    )).scalar() or 0

    # 报告记录数（原 CareerReport 表已删除，S4 改为真值）
    report_count = (await db.execute(
        select(func.count())
        .select_from(ReportRecord)
        .where(ReportRecord.user_id == user_id)
    )).scalar() or 0

    # B2-4：全部快照数（含未匹配）与画像数
    snapshot_count = (await db.execute(
        select(func.count())
        .select_from(ProfileSnapshot)
        .where(ProfileSnapshot.user_id == user_id)
    )).scalar() or 0

    profile_count = (await db.execute(
        select(func.count())
        .select_from(StudentProfile)
        .where(StudentProfile.user_id == user_id)
    )).scalar() or 0

    return AdminUserStats(
        user_id=user.id,
        username=user.username,
        resume_count=resume_count,
        match_count=match_count,
        report_count=report_count,
        chat_session_count=chat_session_count,
        snapshot_count=snapshot_count,
        profile_count=profile_count,
    )


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user profile.

    B2-4 自锁保护：管理员不能**禁用自己**、也不能**取消自己的管理员身份**——
    否则一次误操作就可能把最后一个管理员锁在门外（只能改库救回来）。改别人不受限制。
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    if user.id == current_user.id:
        if update_data.get("status") == 0:
            raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员账号")
        if "role" in update_data and update_data["role"] != USER_ROLE_ADMIN:
            raise HTTPException(status_code=400, detail="不能取消当前登录账号的管理员身份")

    if "password" in update_data:
        # 显式传 null/空串 = 不改密码；只有真给了新密码才重算哈希
        new_password = update_data.pop("password")
        if new_password:
            update_data["password_hash"] = hash_password(new_password)

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=AdminUserResponse)
async def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password.

    密码走**请求体**而非 query（审计 P1-5）：nginx / uvicorn 的访问日志会记录
    query string，明文密码会跟着进日志文件。
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user **and their dependent data**.

    B2-4 修复的真 bug：原先这里只 `db.delete(user)` 一次，而 `chat_sessions`、`resumes`
    两个外键是 `NO ACTION`（`chat_messages.session_id` 同样是 `NO ACTION`）→ 只要该用户
    有过对话或上传过简历，删除就抛 ForeignKeyViolation，接口 500（实测 1520 个用户里
    11 个删不掉，管理端 UI 上就是"点了删除没反应/报错"）。

    现在按外键依赖顺序在**同一事务**内先删子行、再删用户：
    `chat_messages`（经 session 子查询）→ `chat_sessions` → `resumes` → `users`。
    其余关联表（`profile_snapshots` / `report_records` / `student_profiles`）由数据库
    的 `ON DELETE CASCADE` 负责，无需在此重复删除。

    另外（2026-09-25 决定，附件①）：简历的**磁盘文件**也一并删除 —— 此前只删库行，
    文件永久留在 `uploads/user_<id>/`。实测该目录下已有 106 个 PDF 而库里只剩 12 行，
    约 88% 是这么攒出来的。删文件发生在 DB 提交之后，且带路径前缀校验。
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")

    # 简历磁盘路径要在删行之前取出来（删完行就查不到了）
    resume_paths = list(
        (await db.execute(select(Resume.file_path).where(Resume.user_id == user_id)))
        .scalars()
        .all()
    )

    session_ids = select(ChatSession.id).where(ChatSession.user_id == user_id)
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    await db.execute(delete(ChatSession).where(ChatSession.user_id == user_id))
    await db.execute(delete(Resume).where(Resume.user_id == user_id))
    # 最后删用户：数据库级联带走 profile_snapshots / report_records / student_profiles
    # （以及依赖快照的 job_match_records / report_records）
    await db.delete(user)
    await db.flush()

    # `get_db` 的 commit 发生在请求返回**之后**，这里显式提交，保证
    # 「库已删干净 → 才动磁盘」的顺序（重复 commit 无副作用）。
    await db.commit()
    removed_files = _remove_resume_files(user_id, resume_paths)
    logger.info(
        "admin %s deleted user %s (%s) | resumes_rows=%s files_removed=%s",
        current_user.id,
        user_id,
        user.username,
        len(resume_paths),
        removed_files,
    )
