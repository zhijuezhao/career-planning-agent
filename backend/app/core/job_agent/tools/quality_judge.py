from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.job_quality import build_quality_messages


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_DEFAULT_QUALITY = {
    "grade": "D",
    "score": 0,
    "breakdown": {
        "信息完整性": 0,
        "描述质量": 0,
        "要求明确度": 0,
        "薪资信息": 0,
    },
    "strengths": [],
    "weaknesses": ["LLM 评估失败"],
    "summary": "LLM 质量评估未能完成，请检查 LLM 服务配置。",
}


@tool
async def quality_judge(job_data: str) -> dict:
    """Assess the quality of a job posting using LLM evaluation.

    Evaluates completeness, description quality, requirement clarity, and
    salary transparency. Returns a grade (A/B/C/D) with a detailed breakdown.

    Grades:
    - A (≥85): Complete, detailed, clear requirements, transparent salary.
    - B (≥70): Mostly complete, minor gaps.
    - C (≥50): Basic info exists but lacks detail.
    - D (<50): Critical info missing or vague.

    Args:
        job_data: JSON string of the cleaned job record.

    Returns:
        Dict with grade (str), score (int), breakdown (dict),
        strengths (list), weaknesses (list), and summary (str).
    """
    logger.info("Quality judge tool | job_data_len={}", len(job_data))

    try:
        gateway = get_llm_gateway()
        messages = build_quality_messages(job_data)
        # function_key：由管理端「系统配置 > 功能路由」绑定模型；未配置则回落默认模型
        response = await gateway.ainvoke(messages, function_key="job_quality")
        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        cleaned = _strip_json_fences(raw_content)
        data = json.loads(cleaned)
        return {
            "grade": data.get("grade", "D"),
            "score": data.get("score", 0),
            "breakdown": data.get("breakdown", _DEFAULT_QUALITY["breakdown"]),
            "strengths": data.get("strengths", []),
            "weaknesses": data.get("weaknesses", []),
            "summary": data.get("summary", ""),
        }
    except Exception as exc:
        logger.warning("Quality judge LLM call failed | error={}", exc)
        return dict(_DEFAULT_QUALITY)
