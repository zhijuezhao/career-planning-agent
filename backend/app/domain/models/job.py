from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base

# 岗位去重键的标题部分（P2）：生成列，DDL 的唯一来源见 apply_ddl.py / core/dedup_keys.py
_TITLE_KEY_EXPR = "lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))"


class JobProfile(Base):
    __tablename__ = "job_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # P2：`(title_key, company_id)` 是岗位去重粒度。生成列由数据库算，**不可写**
    # （`Computed` 让 SQLAlchemy 把它排除在 INSERT/UPDATE 之外）。
    title_key: Mapped[str | None] = mapped_column(
        String(200), Computed(_TITLE_KEY_EXPR, persisted=True)
    )
    industry: Mapped[str | None] = mapped_column(String(100))
    level: Mapped[str | None] = mapped_column(String(20))
    hard_skills: Mapped[dict | None] = mapped_column(JSONB)
    soft_skills: Mapped[dict | None] = mapped_column(JSONB)
    salary_range: Mapped[str | None] = mapped_column(String(50))
    education_requirement: Mapped[str | None] = mapped_column(String(50))
    experience_requirement: Mapped[str | None] = mapped_column(String(100))
    career_path: Mapped[dict | None] = mapped_column(JSONB)
    transition_paths: Mapped[dict | None] = mapped_column(JSONB)
    # P4a（2026-09-27）：所需证书。来源是职业发展路线表的「所需证书」列 ——
    # 它此前**没有字段可落**（只并进了 requirements 文本），由 `career_fields.py` 确定性回填。
    certificates: Mapped[list | None] = mapped_column(JSONB)
    requirement_intensity: Mapped[dict | None] = mapped_column(JSONB)
    outlook: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    source_data_ids: Mapped[dict | None] = mapped_column(JSONB)
    # B2-2：公司实体外键（DDL 见 apply_ddl.py；NULL = 未识别出公司）
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobRawData(Base):
    __tablename__ = "job_raw_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(50))
    salary: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
