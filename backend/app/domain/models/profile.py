from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class AbilityProfile(Base):
    __tablename__ = "ability_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    direction_tag: Mapped[str] = mapped_column(String(50), default="default")
    intention: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    traits: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    practice: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    soft_skills: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    hard_skills: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    derived_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    completeness_score: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
