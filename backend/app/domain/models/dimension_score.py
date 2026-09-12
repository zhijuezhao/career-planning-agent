from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class DimensionScore(Base):
    __tablename__ = "dimension_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_type: Mapped[str] = mapped_column(String(20), nullable=False)
    profile_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    top_dimension: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_dimension: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_type", "profile_id", "top_dimension", "sub_dimension",
            name="uq_dimension_score_profile_dim",
        ),
    )
