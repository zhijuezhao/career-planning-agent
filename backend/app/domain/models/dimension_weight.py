from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class DimensionWeight(Base):
    __tablename__ = "dimension_weights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_category: Mapped[str] = mapped_column(String(50), nullable=False)
    top_dimension: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "job_category", "top_dimension",
            name="uq_dimension_weight_category_dim",
        ),
    )
