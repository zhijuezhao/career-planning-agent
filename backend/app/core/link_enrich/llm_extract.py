"""L3 层：LLM 精简提取 —— 让模型**挑**定位式，然后我们**自己**取值。

## 核心机制（§4.2 第 3 点）

模型只在"这个域第一次遇到、且规则层没搞定"时被调用**一次**，产出
`{字段: XPath}`；这些 XPath 落 `link_xpath_templates`，此后同域**零调用**。
一次性的语义理解被固化成可复用的确定性定位 —— 省 token 的关键就在这里。

## 三条"不信任模型"的硬约束

1. **只接受候选菜单里的 XPath**：模型自己编的表达式直接丢弃（先比菜单，
   再过 `validate_xpath` 白名单）；
2. **值以"XPath 在本页取到的文本"为准，不以模型抄写的值为准** —— 模型把值抄错、
   或凭想象填一个页面上没有的值，都会在"重新取值"这一步暴露（取不到 → 字段丢弃）。
   这条是"不编造数据"的**机制**，不是提示词里的一句请求；
3. **不写库的表达式不算学过**：校验没过或取不到值的，绝不落模板 —— 否则脏模板会
   在很久以后以"某次导入莫名失败"的形式爆出来。

## 什么时候**不**调用

- 候选菜单为空：没有可复用的定位式可学，花 token 只换到一次性的值，不划算
  （记 `llm_skipped_no_candidates`，而不是静默跳过）；
- 该域本次导入已经学过（每域一次）；
- 预算用尽。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.core.link_enrich.budget import LlmBudget
from app.core.link_enrich.templates import save_template
from app.core.link_enrich.xpath import (
    EXTRACTABLE_FIELDS,
    Candidate,
    apply_xpath,
    build_xpath_candidates,
    validate_xpath,
)
from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.link_enrich import build_link_extract_messages
from app.core.llm.usage import TokenUsage, usage_or_warn

#: L3 的 LLM 功能键（`registry.FUNCTION_KEYS` 里早已为 B3-2 预留，B3-2 把它置为 wired）
FUNCTION_KEY = "job_link_extract"

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class LearnResult:
    """一次 L3 学习的产出。"""

    fields: dict[str, str] = field(default_factory=dict)
    learned: dict[str, str] = field(default_factory=dict)
    usage: TokenUsage = field(default_factory=TokenUsage)
    candidates: int = 0
    #: 为什么没调用（有值时 `fields` 必为空）：no_candidates / budget / error
    skipped: str | None = None
    error: str | None = None
    #: 被拒绝的原因（有界），用于排查"模型给了什么、为什么没采用"
    rejected: list[str] = field(default_factory=list)


def _parse_payload(raw: str) -> dict | None:
    """解析模型返回的 JSON（容错：去 markdown 代码块、截取最外层花括号）。"""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001 - 模型输出格式不稳是常态
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return None
    return parsed if isinstance(parsed, dict) else None


def _extract_field_map(payload: dict) -> dict[str, dict]:
    """取 `{"fields": {...}}`；也容忍模型把字段平铺在顶层。"""
    inner = payload.get("fields")
    if isinstance(inner, dict):
        return {k: v for k, v in inner.items() if isinstance(v, dict)}
    return {
        k: v
        for k, v in payload.items()
        if isinstance(v, dict) and ("xpath" in v or "value" in v)
    }


async def learn_link_fields(
    *,
    domain: str,
    tree: Any,
    text: str,
    session,
    budget: LlmBudget,
    fields: tuple[str, ...] = EXTRACTABLE_FIELDS,
    max_text_chars: int = 4000,
    candidates: list[Candidate] | None = None,
) -> LearnResult:
    """调一次模型学该域的字段定位式，并把有效的落库。

    `session` 为 None 时不落库（仍返回本页的值），便于单测与"只看不学"的场景。
    """
    menu = candidates if candidates is not None else build_xpath_candidates(tree, fields)
    result = LearnResult(candidates=len(menu))
    if not menu:
        result.skipped = "no_candidates"
        logger.info("L3 跳过：本文档没有可用的候选定位式 | domain={}", domain)
        return result

    if not budget.can_call():
        result.skipped = "budget"
        return result

    # 只把**本文档确实缺**的字段交给模型（少问少答 = 少 token）
    wanted = [f for f in fields if f in {c.field for c in menu}]
    messages = build_link_extract_messages(
        domain=domain,
        fields=wanted,
        candidates=[c.as_prompt_item() for c in menu],
        text=(text or "")[:max_text_chars],
    )

    try:
        response = await get_llm_gateway().ainvoke(messages, function_key=FUNCTION_KEY)
    except Exception as exc:  # noqa: BLE001 - LLM 失败只该让这一页退回规则结果
        result.skipped = "error"
        result.error = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning("L3 调用失败（保留规则结果）| domain={} | error={}", domain, exc)
        return result

    usage = usage_or_warn(response, function_key=FUNCTION_KEY)
    budget.spend(usage)
    result.usage = usage

    content = response.content if isinstance(response.content, str) else str(response.content)
    payload = _parse_payload(content)
    if payload is None:
        result.error = "模型输出不是合法 JSON"
        logger.warning("L3 输出无法解析 | domain={} | head={!r:.120}", domain, content[:120])
        return result

    allowed_xpaths = {c.xpath for c in menu}
    for name, item in _extract_field_map(payload).items():
        if name not in EXTRACTABLE_FIELDS or name not in wanted:
            continue
        xpath = str(item.get("xpath") or "").strip()
        if not xpath:
            continue
        if xpath not in allowed_xpaths:
            # 约束 1：菜单之外自己编的，直接丢弃
            result.rejected.append(f"{name}: 非候选表达式")
            continue
        reason = validate_xpath(xpath)
        if reason:
            result.rejected.append(f"{name}: {reason}")
            continue

        # 约束 2：**以重新取到的文本为准**，不信模型抄的值
        values = apply_xpath(tree, xpath, limit=1)
        if not values:
            result.rejected.append(f"{name}: 表达式在本页取不到值")
            continue
        value = values[0].strip()
        if not value:
            continue

        result.fields[name] = value
        result.learned[name] = xpath
        if session is not None:
            # 约束 3：只有"取到了值"的表达式才落库
            await save_template(session, domain, name, xpath)

    logger.info(
        "L3 完成 | domain={} | candidates={} | learned={} | tokens={} | rejected={}",
        domain,
        len(menu),
        sorted(result.learned),
        usage.total_tokens,
        result.rejected[:3],
    )
    return result


__all__ = ["FUNCTION_KEY", "LearnResult", "learn_link_fields"]
