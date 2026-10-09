from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "serial_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("student_profiles.user_id", ondelete="CASCADE"))
    form_raw_json: Mapped[dict] = mapped_column(JSONB, comment="快照时的完整 resume_form")
    five_layers_json: Mapped[dict] = mapped_column(JSONB, comment="五层画像，冻结于快照")
    six_dim_scores_json: Mapped[dict] = mapped_column(JSONB, comment="六维分数，冻结于快照")
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), comment="画像向量，冻结于快照")
    serial_no: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    description: Mapped[str] = mapped_column(String(255), default="")
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "匹配完成标记：NULL=尚未匹配，非空=匹配已完成"
            "（决策 #2，替代 description='matched' 字符串约定）"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
