"""岗位综合画像卡工具（B4-c）。

一次调用 = 一个 `(岗位名, 等级)` 组 → 一份综合卡。

为什么把综合与六维评分**分成两次调用**（而不是合成一次）：

1. `job_portrait` 提示词**已经校准过**，键名稳定性有血泪史（见 `portrait_builder`
   的注释：「模型换键名 → 下游取不到 → 静默落默认值」）。合并成一个新提示词等于
   同时承担"综合质量"和"键名稳定"两份风险；
2. 综合卡是**可审计的中间产物**：能先复核"综合得对不对"，再谈"评分准不准"；
3. 代价只有每组多一次调用（实测约 2 秒），不值得冒险。

失败**不静默**：与 `portrait_builder` 同风格，失败时返回 `aggregate_ok=False` +
`aggregate_error`，让调用方记进统计（`#853` 那次 82 行里 73 行是默认值却报
`failed: 0` 的教训）。
"""

from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.job_agent.aggregate import normalise_card
from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.job_aggregate import build_aggregate_messages

#: 失败重试次数（含首次）。理由与 `portrait_builder` 相同：
#: 偶发失败（超时/限流）值得一次重试，但必须把最终失败暴露给调用方。
_MAX_ATTEMPTS = 2


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


@tool
async def job_aggregator(
    group_input: str,
    role: str,
    level: str,
    posting_count: int,
) -> dict:
    """把一组同岗位同等级的招聘综合成一份「岗位综合画像卡」。

    Args:
        group_input: `aggregate.build_group_input()` 产出的紧凑记录文本。
        role: 岗位名（原始写法，用于回显与审计）。
        level: 本次等级（初级/中级/高级/不限）。
        posting_count: 本组条数（写进卡片，便于复核"综合了多少条"）。

    Returns:
        Dict：综合卡的各个键 + ``aggregate_ok`` (bool) + ``aggregate_error`` (str | None)
        + ``aggregate_problems`` (list[str]，键缺失/键名不一致等可复核的问题)。
    """
    logger.info(
        "Job aggregator | role={!r} | level={} | count={} | input_len={}",
        role,
        level,
        posting_count,
        len(group_input),
    )

    last_error: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            gateway = get_llm_gateway()
            messages = build_aggregate_messages(
                group_input, role=role, level=level, count=posting_count
            )
            response = await gateway.ainvoke(messages, function_key="job_aggregate")
            raw = response.content if isinstance(response.content, str) else str(response.content)

            data = json.loads(_strip_json_fences(raw))
            card, problems = normalise_card(
                data, role=role, level=level, posting_count=posting_count
            )
            if not card:
                raise ValueError(f"综合卡不可用：{problems}")

            if problems:
                logger.info("综合卡有可复核的问题 | role={!r} | problems={}", role, problems)
            return {
                **card,
                "aggregate_ok": True,
                "aggregate_error": None,
                "aggregate_problems": problems,
            }
        except Exception as exc:  # noqa: BLE001 - 重试后仍失败则如实上报
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Job aggregator 第 {}/{} 次失败 | role={!r} | error={}",
                attempt,
                _MAX_ATTEMPTS,
                role,
                last_error,
            )

    return {
        "role": role,
        "level": level,
        "posting_count": posting_count,
        "aggregate_ok": False,
        "aggregate_error": last_error,
        "aggregate_problems": [],
    }
