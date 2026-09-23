from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.resume_parsing import build_resume_parsing_messages
from app.core.resume_agent.schemas import ParsedResume


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_resume_json(raw_text: str) -> ParsedResume:
    cleaned = _strip_json_fences(raw_text)
    data = json.loads(cleaned)
    return ParsedResume.model_validate(data)


async def _parse_resume(resume_text: str) -> dict:
    gateway = get_llm_gateway()
    messages = build_resume_parsing_messages(resume_text)

    # function_key="resume_parse"：由管理端「系统配置 > 功能路由」绑定（B4-1）；
    # 未绑定则回退 env `resume_llm_model`，都没有则用网关默认模型。
    response = await gateway.ainvoke(messages, function_key="resume_parse")
    raw_content = response.content if isinstance(response.content, str) else str(response.content)

    try:
        parsed = parse_resume_json(raw_content)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Resume parsing JSON decode failed: {} | raw={}", exc, raw_content[:200])
        parsed = ParsedResume()

    return parsed.model_dump()


@tool
async def resume_parser(resume_text: str) -> dict:
    """Parse resume text into structured ParsedResume using LLM.

    Args:
        resume_text: Raw text extracted from a PDF resume.

    Returns:
        Dict representation of ParsedResume with all six layers.
    """
    return await _parse_resume(resume_text)
