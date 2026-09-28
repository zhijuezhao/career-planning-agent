"""L3/L4 的 token 预算闸门（主计划 §4.5）。

为什么需要它：链接富化的 LLM 层是**可选**的（`LINK_ENRICH_LLM_ENABLED` 默认关），
但一旦打开，花费就取决于"这张表里有多少个不同的域" —— 那是上传者决定的，不是我们。
所以必须有闸门，且闸门要**在调用前判断、调用后记账**。

## 一条规则，不要两种解释

`max_calls` / `max_tokens` 传 **0 或负数 = 不限制**。
想彻底关掉 LLM 层请用 `LINK_ENRICH_LLM_ENABLED=false`（专门的开关）。

这样定是因为"0 到底是不限制还是禁止"是个会让人误判的坑：两种约定都有人用，
而这里已经有了一个语义明确的开关，就不该再让数值 0 承担第二种含义。

## 超限后的行为（§4.5）

**立即停止后续 LLM 调用，保留已得到的规则结果**（L1/L2 的字段照常合并落库），
并把 `budget_exceeded=True` 写进统计 —— 是"少富化几行"，不是"整单失败"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from app.core.llm.usage import TokenUsage


@dataclass
class LlmBudget:
    """一次导入内的 LLM 花费账本。"""

    max_calls: int = 10
    max_tokens: int = 50_000
    calls: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    #: 被闸门挡下过（用于统计与告警，不等同于"这次一定没跑"）
    blocked: bool = False

    def _call_limit_hit(self) -> bool:
        return self.max_calls > 0 and self.calls >= self.max_calls

    def _token_limit_hit(self) -> bool:
        return self.max_tokens > 0 and self.usage.total_tokens >= self.max_tokens

    @property
    def exhausted(self) -> bool:
        return self._call_limit_hit() or self._token_limit_hit()

    def can_call(self) -> bool:
        """能否再发起一次调用。被挡时把 `blocked` 置起来并记一次日志。"""
        if self._call_limit_hit():
            self.blocked = True
            logger.info(
                "Link Enrich LLM 预算用尽（调用次数）| calls={}/{}", self.calls, self.max_calls
            )
            return False
        if self._token_limit_hit():
            self.blocked = True
            logger.info(
                "Link Enrich LLM 预算用尽（token）| tokens={}/{}",
                self.usage.total_tokens,
                self.max_tokens,
            )
            return False
        return True

    def spend(self, usage: TokenUsage | None) -> None:
        """记一次调用的花费（用量缺失按 0 记，但调用次数照记）。"""
        self.calls += 1
        if usage:
            self.usage = self.usage + usage

    def as_stats(self) -> dict:
        return {
            "llm_calls": self.calls,
            "tokens_used": self.usage.total_tokens,
            "tokens_input": self.usage.input_tokens,
            "tokens_output": self.usage.output_tokens,
            "budget_exceeded": self.blocked or self.exhausted,
        }


__all__ = ["LlmBudget"]
