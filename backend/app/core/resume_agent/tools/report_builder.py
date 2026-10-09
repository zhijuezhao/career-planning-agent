from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.profile_analysis import build_report_messages
from app.core.safety.filter import append_disclaimer


async def _build_report(
    five_layers: dict,
    dimension_scoring: dict | None,
    basic_info: dict,
    matching_results: list[dict] | None = None,
) -> str:
    gateway = get_llm_gateway()

    messages = build_report_messages(
        five_layers_json=json.dumps(five_layers, ensure_ascii=False, indent=2),
        dimension_scoring_json=json.dumps(
            dimension_scoring or {}, ensure_ascii=False, indent=2
        ),
        basic_info_json=json.dumps(basic_info, ensure_ascii=False, indent=2),
        matching_results_json=json.dumps(matching_results or [], ensure_ascii=False, indent=2),
    )

    response = await gateway.ainvoke(messages)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    report = append_disclaimer(raw.strip())
    logger.info("Report generated | length={}", len(report))
    return report


@tool
async def report_builder(
    five_layers: dict,
    dimension_scoring: dict | None = None,
    basic_info: dict | None = None,
) -> dict:
    """Generate a career analysis report from ability portrait and dimension scores.

    Args:
        five_layers: Five-layer ability portrait dict (intention/traits/practice/soft_skills/hard_skills).
        dimension_scoring: Optional DimensionScoring dict with 6-dimension scores.
        basic_info: Optional basic info dict (name/school/degree etc.).

    Returns:
        Dict with report_text (str, Markdown with disclaimer appended).
    """
    report_text = await _build_report(
        five_layers=five_layers,
        dimension_scoring=dimension_scoring,
        basic_info=basic_info or {},
    )
    return {"report_text": report_text}
