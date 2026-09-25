"""岗位 ↔ 公司 关联（B2-5）。

语义：`job_profiles` 仍按**岗位名**去重（一个岗位画像对应一种职位），
但同一种职位可能被**多家公司**同时招 —— 该表记录每个 (岗位, 公司) 组合，
于是既能查「某家公司有多少个岗位」，也能查「某个岗位有多少家公司在招」。

- `hit_count`：该组合在导入里出现过的行数（同一公司多次导入同一岗位时会累加）；
- `job_profiles.company_id` 保留为「主公司」（**首次**建立关联的那家，不再被后来者覆盖）；
- `companies.job_count` 由本表重算（count(distinct job_profile_id)），保证不会陈旧。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class JobCompanyLink(Base):
    __tablename__ = "job_company_links"
    __table_args__ = (
        UniqueConstraint("job_profile_id", "company_id", name="uq_job_company_links"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_profiles.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), default="import", server_default="import")
    hit_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["JobCompanyLink"]
