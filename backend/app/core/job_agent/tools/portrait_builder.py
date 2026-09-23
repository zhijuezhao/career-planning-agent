from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.job_portrait import build_portrait_messages


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_DEFAULT_PORTRAIT = {
    "five_dimensions": {
        "technical": {"score": 3, "key_skills": []},
        "experience": {"score": 3, "key_skills": []},
        "soft_skills": {"score": 3, "key_skills": []},
        "education": {"score": 3, "key_skills": []},
        "responsibility": {"score": 3, "key_skills": []},
    },
    "career_paths": [],
    "transition_roles": [],
    "outlook": {
        "outlook": "成熟",
        "trend": "",
        "risk_factors": [],
    },
    "summary": "",
}


@tool
async def portrait_builder(job_data: str) -> dict:
    """Generate a deep job portrait from cleaned job data using LLM.

    Produces a five-dimension profile (technical, experience, soft skills,
    education, responsibility), career paths, transition directions, and
    outlook assessment.

    Args:
        job_data: JSON string of the cleaned job record.

    Returns:
        Dict with five_dimensions (dict), career_paths (list),
        transition_roles (list), outlook (dict), and summary (str).
    """
    logger.info("Portrait builder tool | job_data_len={}", len(job_data))

    try:
        gateway = get_llm_gateway()
        messages = build_portrait_messages(job_data)
        # function_key：由管理端「系统配置 > 功能路由」绑定模型；未配置则回落默认模型
        response = await gateway.ainvoke(messages, function_key="job_portrait")
        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        cleaned = _strip_json_fences(raw_content)
        data = json.loads(cleaned)
        return {
            "five_dimensions": data.get("five_dimensions", _DEFAULT_PORTRAIT["five_dimensions"]),
            "career_paths": data.get("career_paths", []),
            "transition_roles": data.get("transition_roles", []),
            "outlook": data.get("outlook", _DEFAULT_PORTRAIT["outlook"]),
            "summary": data.get("summary", ""),
        }
    except Exception as exc:
        logger.warning("Portrait builder LLM call failed | error={}", exc)
        return dict(_DEFAULT_PORTRAIT)
