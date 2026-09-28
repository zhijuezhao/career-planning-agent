"""`link_xpath_templates` 的 ORM 映射（B3-2 的 L2 层：省 token 的核心资产）。

**表不是本模块建的**：DDL 早在批 2 就建好了（`apply_ddl.py:205-221`），
但一直没有 Python 侧映射 —— 表在库里躺着，没有任何代码读写它。与
`link_fetch_cache` 同一情形（B3-1 也只补了映射）。**本轮零 DDL 改动。**

## 这张表为什么是"省 token 的核心"

主计划 §4.2 第 3 点：**把一次性的"语义理解"固化为可复用的"确定性定位"**。
模型只在"这个域第一次出现"时被调用一次，产出的 XPath 落入本表；此后同域的
第 2..N 行/页**零调用**直接用 XPath 取值。所以这张表的价值 = 已学域数 × 后续页数。

## 失效与自愈

模板会失效（站点改版、A/B 版式、不同子类页面）。所以：

- `hit_count` / `miss_count` 都记：命中加分、未命中加分，`last_ok_at` 记最后一次成功；
- 连续未命中不"永久放弃"这张模板，而是在 L3 重新学习时**覆盖**它（自愈）——
  因为"某页版式不同"很常见，一旦放弃就永远回不去零调用。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class LinkXpathTemplate(Base):
    __tablename__ = "link_xpath_templates"
    __table_args__ = (UniqueConstraint("domain", "field", name="uq_link_xpath_templates_domain_field"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    #: 域名（小写、去 www.，与 `link_enrich.urls.domain_of` 同一口径）
    domain: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 行字段名（company/city/salary/...），与 `merge.LINKABLE_FIELDS` 同一套键
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    #: 定位表达式（**模型产出**，执行前必须过 `xpath.validate_xpath` 白名单校验）
    xpath: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    miss_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
