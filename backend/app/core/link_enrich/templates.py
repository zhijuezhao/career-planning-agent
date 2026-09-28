"""L2 层的模板仓库：`link_xpath_templates` 的读写。

这一层很薄，但有两件事必须做对：

1. **写库前一律过 `validate_xpath()`**：模板是**模型产出**的表达式，落库等于把它
   持久化给未来所有导入用。脏表达式一旦进库，会在很久以后以"某次导入莫名失败"
   的形式爆出来。所以入库是最后一道可以拦的地方。
2. **未命中不删、只记 miss**：模板失效的常见原因是"某页版式不同"，不是"这个域永远
   变了"。删掉就等于永久放弃零调用路径。自愈方式是在 L3 重新学到新表达式时**覆盖**。
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.link_enrich.xpath import validate_xpath
from app.domain.models.link_xpath_template import LinkXpathTemplate


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_templates(session: AsyncSession, domain: str) -> dict[str, str]:
    """取该域已学的 `{field: xpath}`。读失败按"没学过"处理（退化成 L3 再学一次，
    比让整单失败合理）。"""
    if not domain:
        return {}
    try:
        rows = (
            await session.execute(
                select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
            )
        ).scalars().all()
    except Exception as exc:  # noqa: BLE001 - 模板表读失败不该打断导入
        logger.warning("读 XPath 模板失败（按未命中处理）| domain={} | error={}", domain, exc)
        return {}

    out: dict[str, str] = {}
    for row in rows:
        if validate_xpath(row.xpath):
            # 库里已有脏数据（历史遗留/人工改坏）：不执行、也不在这里删，
            # 交给下一次学习覆盖
            logger.warning("跳过库中未通过校验的 XPath | domain={} | field={}", domain, row.field)
            continue
        out[row.field] = row.xpath
    return out


async def save_template(
    session: AsyncSession,
    domain: str,
    field: str,
    xpath: str,
    *,
    now: datetime | None = None,
) -> bool:
    """写入/更新一条模板。返回是否真的写入（校验不过则 False）。"""
    reason = validate_xpath(xpath)
    if reason:
        logger.warning(
            "拒绝入库未通过校验的 XPath | domain={} | field={} | reason={}", domain, field, reason
        )
        return False
    if not domain:
        return False

    try:
        row = (
            await session.execute(
                select(LinkXpathTemplate)
                .where(LinkXpathTemplate.domain == domain, LinkXpathTemplate.field == field)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(
                LinkXpathTemplate(
                    domain=domain,
                    field=field,
                    xpath=xpath,
                    hit_count=1,
                    miss_count=0,
                    last_ok_at=now or _now(),
                )
            )
        else:
            # 自愈：模型新学的表达式覆盖旧的（版式变了就换新的）
            row.xpath = xpath
            row.hit_count = (row.hit_count or 0) + 1
            row.last_ok_at = now or _now()
        await session.flush()
        return True
    except Exception as exc:  # noqa: BLE001 - 学模板失败只该少省点 token
        logger.warning("写 XPath 模板失败（忽略）| domain={} | field={} | error={}", domain, field, exc)
        return False


async def record_outcome(
    session: AsyncSession,
    domain: str,
    field: str,
    *,
    hit: bool,
    now: datetime | None = None,
) -> None:
    """记一次命中/未命中（供"模板是否还有效"的观测用）。失败只告警。"""
    if not domain:
        return
    try:
        row = (
            await session.execute(
                select(LinkXpathTemplate)
                .where(LinkXpathTemplate.domain == domain, LinkXpathTemplate.field == field)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        if hit:
            row.hit_count = (row.hit_count or 0) + 1
            row.last_ok_at = now or _now()
        else:
            row.miss_count = (row.miss_count or 0) + 1
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.debug("记模板命中/未命中失败（忽略）| domain={} | field={} | error={}", domain, field, exc)


__all__ = ["load_templates", "record_outcome", "save_template"]
