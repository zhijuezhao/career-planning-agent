from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.api.v1.auth import require_auth
from app.domain.models.user import User


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
