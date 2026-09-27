"""公司实体（B2-2，需求 3）。

表由 `backend/scripts/apply_ddl.py` 落地（B2-0）。`job_count` 是**冗余统计列**，
由 `company_service.refresh_job_count()` 依据 `job_company_links` 实算后回写
（2026-09-27 任务 3 起：公司归属的唯一真相是关联表，`job_profiles.company_id` 已删除），
避免每次列表都做一次 group by。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    #: 规模（存导入表里的原文，如 `1000-9999人`；将来要筛选再加枚举码列）
    scale: Mapped[str | None] = mapped_column(String(50))
    #: 地域（省/直辖市）—— 与 `city` 组成**省市两级**，对应管理端「先选省、再选市」的级联筛选
    region: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(50))
    job_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["Company"]
