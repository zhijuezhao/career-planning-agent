from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class JobUpdateSchedule(Base):
    __tablename__ = "job_update_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="web")
    source_url: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(100))
    keywords: Mapped[str | None] = mapped_column(String(300))

    interval_days: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    min_interval_days: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    max_interval_days: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_change_rate: Mapped[float | None] = mapped_column(Float)
    last_item_count: Mapped[int | None] = mapped_column(Integer)
    consecutive_no_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(default=True)
    job_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IndustryReport(Base):
    __tablename__ = "industry_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[dict | None] = mapped_column(JSONB)
    source_urls: Mapped[list | None] = mapped_column(JSONB)
    keywords: Mapped[str | None] = mapped_column(String(300))
    item_count: Mapped[int | None] = mapped_column(Integer)
    is_ai_enriched: Mapped[bool] = mapped_column(default=True)
    report_hash: Mapped[str | None] = mapped_column(String(64))

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
