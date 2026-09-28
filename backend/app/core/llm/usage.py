"""LLM 用量计量：从 LangChain 的 `AIMessage` 里取 token 数。

## 为什么需要这个模块

截止 B3-1，**全仓没有任何 LLM 用量计量**（实测：grep `usage_metadata|token_usage|
prompt_tokens|completion_tokens|total_tokens` 只命中无关的配置项与两个从未被填充的
`tokens_used` 列）。于是"一次调用花了多少 token"没有任何地方知道 ——

- `reports.tokens_used` / `chat_messages.tokens_used` 永远是 0（`chat_service.py:95`
  直接硬编码 `tokens_used=0`）；
- B3-2 的预算闸门（`LINK_ENRICH_MAX_TOKENS`）没有数据来源。

`LLMGateway.ainvoke()` 返回的是**原始** `AIMessage`，而 LangChain 的 OpenAI 适配器
**已经**把用量填在 `message.usage_metadata` 里（2026-09-27 实测：
`{'input_tokens': 9, 'output_tokens': 1, 'total_tokens': 10, ...}`）。
所以这里不引入新依赖，只把已有的东西读出来。

## 两个必须容错的地方

1. **字段可能不存在**：不是所有供应商/适配器都回 usage。缺失时返回全 0，
   **不是**抛异常 —— 计量失败不该让业务调用失败。
2. **形状可能不同**：`usage_metadata` 通常是 dict，但在 pydantic 模型上也可能是
   带属性的对象。两种都认。

另外兼容 `response_metadata["token_usage"]`（部分路径走那里）。实测本仓的
longcat/deepseek 适配器**只有** `usage_metadata`，`token_usage` 是缺的 —— 所以
两者都要读，不能只认一个。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class TokenUsage:
    """一次调用的用量。`total` 缺失时按 input+output 兜底。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        return self.total_tokens == 0 and self.input_tokens == 0 and self.output_tokens == 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


EMPTY_USAGE = TokenUsage()


def _as_int(value: Any) -> int:
    """宽进：字符串数字、None、float 都要能落到 int（缺失即 0）。"""
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read(mapping: Any, key: str) -> Any:
    """dict 与"带属性的对象"都能读（pydantic 模型不是 dict）。"""
    if mapping is None:
        return None
    if isinstance(mapping, dict):
        return mapping.get(key)
    return getattr(mapping, key, None)


def extract_usage(message: Any) -> TokenUsage:
    """从 LLM 响应里取用量；取不到返回 `EMPTY_USAGE`（永不抛异常）。

    优先 `usage_metadata`，其次 `response_metadata["token_usage"]`。
    """
    if message is None:
        return EMPTY_USAGE

    raw = _read(message, "usage_metadata")
    if not raw:
        raw = _read(_read(message, "response_metadata"), "token_usage")
    if not raw:
        return EMPTY_USAGE

    prompt = _as_int(_read(raw, "input_tokens") or _read(raw, "prompt_tokens"))
    completion = _as_int(_read(raw, "output_tokens") or _read(raw, "completion_tokens"))
    total = _as_int(_read(raw, "total_tokens"))
    if not total:
        total = prompt + completion
    return TokenUsage(input_tokens=prompt, output_tokens=completion, total_tokens=total)


def usage_or_warn(message: Any, *, function_key: str | None = None) -> TokenUsage:
    """取用量；取不到时**告警一次**。

    预算闸门依赖用量：如果供应商突然不回报用量，闸门会退化成"只数调用次数"。
    那种退化必须可见（否则"预算没超"会变成假象），所以在真正依赖它的地方用这个。
    """
    usage = extract_usage(message)
    if usage.is_empty:
        logger.warning(
            "LLM 响应未包含用量信息，token 预算将无法累计 | function_key={}", function_key
        )
    return usage


__all__ = ["EMPTY_USAGE", "TokenUsage", "extract_usage", "usage_or_warn"]
