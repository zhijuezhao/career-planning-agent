from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base

#: `data_import_jobs.status` 的取值（**前端契约**，前端只认这几个）。
#:
#: `awaiting_confirmation` 是 B3（2026-10-03）新增的**切片暂停闸门**：
#: 一片跑完就停在这里，等管理员点"继续下一片"再处理下一片。
#: ⚠️ 这个值是 **21 个字符** —— 列宽必须 ≥ 21（建表时代是 `VARCHAR(20)`，
#: 已由 `apply_ddl.py` 与新增的 alembic 版本一起加宽到 32）。
IMPORT_STATUS_PENDING = "pending"
IMPORT_STATUS_PROCESSING = "processing"
IMPORT_STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
IMPORT_STATUS_COMPLETED = "completed"
IMPORT_STATUS_FAILED = "failed"

#: 允许「开始/继续处理」的状态（`POST /{job_id}/process` 的准入集合）
IMPORT_PROCESSABLE_STATUSES = frozenset(
    {IMPORT_STATUS_PENDING, IMPORT_STATUS_FAILED, IMPORT_STATUS_AWAITING_CONFIRMATION}
)

#: 终态（前端轮询 / SSE 见到这些就停）
IMPORT_TERMINAL_STATUSES = frozenset({IMPORT_STATUS_COMPLETED, IMPORT_STATUS_FAILED})


class DataImportJob(Base):
    __tablename__ = "data_import_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 32 而不是 20：`awaiting_confirmation` 有 21 个字符（B3 切片闸门）
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=IMPORT_STATUS_PENDING,
        server_default=IMPORT_STATUS_PENDING,
    )
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSONB)
    # B2-2：落库统计（persist 阶段写入）；B3 会往里加链接解析/token 统计
    stats: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
