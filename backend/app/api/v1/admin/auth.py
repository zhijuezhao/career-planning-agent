from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.infrastructure.security import create_access_token, verify_password
from app.schemas.user import TokenResponse, UserLogin

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def admin_login(data: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """管理员登录（S2）：仅 role=admin 且 status=1 的账号可换取 token。

    与学生端 `/api/v1/auth/login` 分离 —— 学生账号在此一律 403，
    修复「任何学生账号都能拿到 token 进管理端」的原缺陷。
    """
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    # 账号不存在 / 密码错误：统一 401，不区分，避免被用来探测账号是否存在
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if user.status != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非管理员账号")

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token)


async def require_admin(current_user: User = Depends(require_auth)) -> User:
    """Dependency that requires the current user to have admin role.

    Raises:
        HTTPException: 403 if the user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required",
        )
    return current_user
