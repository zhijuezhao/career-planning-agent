"""匹配明细（B2-3，需求 3）：一次匹配运行里「快照 × 岗位」的逐条结果。

表由 `backend/scripts/apply_ddl.py` 落地（B2-0）。语义约定：

- **同一快照重复匹配 = 覆盖**（`match_record_service.save_match_run` 先删该快照的旧行再写入），
  这样明细表不会随反复点「开始匹配」无限膨胀，页面看到的永远是最近一次运行；
- `rank` 从 1 开始，按 `score` 倒序；
- `status='failed'` 表示该岗位**单个打分失败**（例如维度分数查询异常），此时 score/distance 为空、
  `analysis` 里带 `error`；单条失败不影响其他岗位（B2-3 起的行级容错）；
- `duration_ms` 记录本次运行耗时（同一运行的所有行相同）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class JobMatchRecord(Base):
    __tablename__ = "job_match_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # profile_snapshots.id 是 integer（不是 bigint），外键列必须同型
    profile_snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    job_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_profiles.id", ondelete="CASCADE"), nullable=False
    )
    # 注意：列名是 PG 的保留倾向字，SQLAlchemy 生成 SQL 时会自动加引号
    rank: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    score: Mapped[float | None] = mapped_column(Float)
    distance: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="success", server_default="success")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analysis: Mapped[dict | None] = mapped_column(JSONB)


__all__ = ["JobMatchRecord"]
