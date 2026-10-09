from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class ReportRecord(Base):
    __tablename__ = "report_records"
    __table_args__ = (UniqueConstraint("user_id", "serial_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_snapshot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("profile_snapshots.id", ondelete="CASCADE"))
    serial_no: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    description: Mapped[str] = mapped_column(String(255), default="")
    report_text: Mapped[str] = mapped_column(Text)
    word_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def version(self) -> int:
        """导出版本：由 report_service 按 user 计数生成后填充。表内不落列。"""
        raise NotImplementedError  # 实际由 service 生成，见 Task 6
