"""模型配置中心（B2-1）ORM：供应商 → 模型 → 功能路由 三层。

表结构由 `backend/scripts/apply_ddl.py`（方案 A，幂等）落地；此处只做映射。
`api_key_encrypted` 存密文（`enc:v1:` 前缀，见 `app/core/llm/secrets.py`），
历史明文值仍可被 `decrypt_secret()` 兼容读取。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class LLMProvider(Base):
    """模型供应商（系统配置 > 供应商）。"""

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMModel(Base):
    """模型目录（挂在供应商下）。kind=chat 走网关，kind=embedding 走向量客户端。"""

    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_name", name="uq_llm_models_provider_model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="chat", server_default="chat")
    # embedding 专用：输出维度（DB 向量列固定 vector(1024)，切换模型必须核对）
    dim: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(Float)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMRoute(Base):
    """功能键 → 模型绑定（唯一）。无对应行 = 未配置，回退 env 默认行为。"""

    __tablename__ = "llm_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    function_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_models.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["LLMModel", "LLMProvider", "LLMRoute"]
