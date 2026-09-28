"""`link_fetch_cache` 的 ORM 映射（B3-1 Link Enrich 的抓取缓存）。

**表不是本模块建的**：DDL 早已由 `scripts/apply_ddl.py` 的批 2 建好
（`apply_ddl.py:222-237`），只是一直没有 Python 侧的映射 —— 表和列都在库里，
却没有任何代码读写它。B3-1 需要它来「同域同页不重复抓」（主计划 §4.2 第 6 点），
所以这里补上 ORM，**不改 DDL**。

`content` 存的是**提取结果**（JSON 文本：字段 + provenance + 正文），不是原始 HTML：

- 缓存要解决的是"别再发一次请求"，而提取是纯本地的确定性步骤、几乎不花时间；
- 原始 HTML 动辄几百 KB，存它会让这张表迅速膨胀，而岗位字段只用得上几十个；
- 存 JSON 也避免了"HTML 变了但缓存还是旧的"这种更难排查的问题。

JSON 里带 `v`（`CACHE_VERSION`）。**提取逻辑升级时必须 +1** —— 否则老缓存会被
新代码按新口径解读，出现"改了代码但线上没变化"的幽灵 bug。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class LinkFetchCache(Base):
    __tablename__ = "link_fetch_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    #: sha256(规范化 URL) —— 与 `link_enrich.urls.url_hash` 同一算法，64 位十六进制
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(200))
    status_code: Mapped[int | None] = mapped_column(Integer)
    #: 提取结果的 JSON 文本（见模块 docstring：不存原始 HTML）
    content: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: NULL 表示"永不过期"（当前实现总会写值）
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
