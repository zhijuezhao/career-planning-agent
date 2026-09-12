from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.industry_report import build_industry_report_messages
from app.core.safety.filter import append_disclaimer


@tool
async def report_summarizer(data: str, industry: str | None = None) -> dict:
    """Generate a summary report from collected job/industry data using LLM.

    Aggregates collected data and produces an industry trend report covering
    hot jobs, salary analysis, skill changes, and outlook.

    Args:
        data: JSON string of collected data (search results, job data, etc.).
        industry: Optional industry name for context (e.g. "互联网/IT").

    Returns:
        Dict with summary (str), sections (dict), source (str), and
        is_ai_enriched (bool).
    """
    logger.info("Report summarizer tool | data_len={} | industry={!r:.40}", len(data), industry)

    # Enhance input with industry context if provided
    enhanced_data = data
    if industry:
        enhanced_data = f"行业: {industry}\n\n{data}"

    try:
        gateway = get_llm_gateway()
        messages = build_industry_report_messages(enhanced_data)
        response = await gateway.ainvoke(messages)
        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        # Append safety disclaimer
        report_text = append_disclaimer(raw_content)

        # Parse sections from the markdown report
        sections = _parse_sections(report_text)

        logger.info("Report generated | industry={!r:.40} | chars={}",
                    industry, len(report_text))
        return {
            "summary": report_text,
            "sections": sections,
            "source": "llm",
            "is_ai_enriched": True,
            "industry": industry,
        }
    except Exception as exc:
        logger.warning("Report summarizer LLM call failed | error={}", exc)
        return {
            "summary": "",
            "sections": {
                "行业概览": "",
                "热门岗位趋势": "",
                "薪资水平分析": "",
                "技能需求变化": "",
                "行业前景展望": "",
            },
            "source": "pending",
            "is_ai_enriched": False,
            "error": str(exc),
        }


def _parse_sections(markdown_text: str) -> dict[str, str]:
    """Parse a Markdown report into sections by ### headers."""
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    section_titles = ["行业概览", "热门岗位趋势", "薪资水平分析", "技能需求变化", "行业前景展望"]

    for line in markdown_text.split("\n"):
        # Check if line is a section header
        matched = False
        for title in section_titles:
            if line.strip().startswith("###") and title in line:
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = title
                current_lines = []
                matched = True
                break
        if not matched:
            current_lines.append(line)

    # Save last section
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections
