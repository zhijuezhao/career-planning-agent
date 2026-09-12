from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.safety.filter import append_disclaimer, check_content


@tool
async def content_safety_check(text: str) -> dict:
    """Check text for content safety violations (discrimination, false promises).

    Applies a disclaimer and returns the sanitized text along with the check result.

    Args:
        text: The text content to check.

    Returns:
        Dict with is_safe (bool), violation_type (str or None),
        reason (str or None), and sanitized_text (str with disclaimer appended).
    """
    result = check_content(text)
    sanitized = append_disclaimer(text)

    logger.info(
        "Safety check | is_safe={} | violation={}",
        result.is_safe,
        result.violation_type,
    )

    return {
        "is_safe": result.is_safe,
        "violation_type": result.violation_type.value if result.violation_type else None,
        "reason": result.reason,
        "sanitized_text": sanitized,
    }
