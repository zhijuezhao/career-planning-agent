from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class JobProfile(Base):
    __tablename__ = "job_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    level: Mapped[str | None] = mapped_column(String(20))
    hard_skills: Mapped[dict | None] = mapped_column(JSONB)
    soft_skills: Mapped[dict | None] = mapped_column(JSONB)
    salary_range: Mapped[str | None] = mapped_column(String(50))
    education_requirement: Mapped[str | None] = mapped_column(String(50))
    experience_requirement: Mapped[str | None] = mapped_column(String(100))
    career_path: Mapped[dict | None] = mapped_column(JSONB)
    transition_paths: Mapped[dict | None] = mapped_column(JSONB)
    requirement_intensity: Mapped[dict | None] = mapped_column(JSONB)
    outlook: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    source_data_ids: Mapped[dict | None] = mapped_column(JSONB)
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
