from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger


@tool
async def generate_career_report(
    user_id: int,
    profile_id: int,
    target_job: str | None = None,
) -> dict:
    """Generate a comprehensive career development report with Word export.

    Args:
        user_id: The user's ID.
        profile_id: The ability profile ID.
        target_job: Optional target job title.

    Returns:
        Dict with report data or error message.
    """
    try:
        from app.domain.services.report_service import create_report
        from app.infrastructure.database import async_session_factory

        async with async_session_factory() as session:
            report = await create_report(
                user_id=user_id,
                profile_id=profile_id,
                target_job=target_job,
                session=session,
            )

            return {
                "success": True,
                "report_id": report.id,
                "version": report.version,
                "target_job": report.target_job,
                "word_file_path": report.word_file_path,
                "report_summary": report.report_content.get("report_text", "")[:500] if report.report_content else "",
            }
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("generate_career_report tool error | user_id={} | error={}", user_id, exc)
        return {"error": f"Report generation failed: {exc}"}
