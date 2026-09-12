from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.job_extract import build_extract_messages


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_DEFAULT_EXTRACT = {
    "title": None,
    "company": None,
    "city": None,
    "salary": None,
    "description": None,
    "requirements": None,
    "education_requirement": None,
    "experience_requirement": None,
    "hard_skills": [],
    "soft_skills": [],
}


@tool
async def job_extractor(job_text: str) -> dict:
    """Extract structured job information from raw text using LLM.

    Parses a raw job posting text and extracts fields such as title, company,
    city, salary, description, requirements, education, experience, and skills.

    Args:
        job_text: Raw job posting text.

    Returns:
        Dict with extracted fields (title, company, city, salary, description,
        requirements, skills, etc.).
    """
    logger.info("Job extractor tool | job_text_len={}", len(job_text))

    try:
        gateway = get_llm_gateway()
        messages = build_extract_messages(job_text)
        response = await gateway.ainvoke(messages)
        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        cleaned = _strip_json_fences(raw_content)
        data = json.loads(cleaned)
        return {
            "title": data.get("title"),
            "company": data.get("company"),
            "city": data.get("city"),
            "salary": data.get("salary"),
            "description": data.get("description"),
            "requirements": data.get("requirements"),
            "education_requirement": data.get("education_requirement"),
            "experience_requirement": data.get("experience_requirement"),
            "hard_skills": data.get("hard_skills", []),
            "soft_skills": data.get("soft_skills", []),
        }
    except Exception as exc:
        logger.warning("Job extractor LLM call failed | error={}", exc)
        return dict(_DEFAULT_EXTRACT)
