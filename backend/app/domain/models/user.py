from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.roles import DEFAULT_USER_ROLE
from app.infrastructure.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(100), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    # B2-4：联系方式。**列由 B2-0 的 apply_ddl.py 建好**（qq VARCHAR(20) / wechat VARCHAR(50)，
    # 均可空），这里只补 ORM 映射与管理端读写，不需要新的 DDL。
    qq: Mapped[str | None] = mapped_column(String(20))
    wechat: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default=DEFAULT_USER_ROLE)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
