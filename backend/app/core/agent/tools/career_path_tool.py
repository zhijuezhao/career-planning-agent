from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger


@tool
async def create_career_path(
    user_id: int,
    profile_id: int,
    target_job_id: int,
    current_stage: str = "在校学生",
) -> dict:
    """Generate a career development path for a user.

    Args:
        user_id: The user's ID.
        profile_id: The ability profile ID.
        target_job_id: The target job profile ID.
        current_stage: Current career stage (default "在校学生").

    Returns:
        Dict with career path data or error message.
    """
    try:
        from app.core.matching.path_planner import generate_career_path
        from app.infrastructure.database import async_session_factory

        async with async_session_factory() as session:
            path = await generate_career_path(
                user_id=user_id,
                profile_id=profile_id,
                target_job_id=target_job_id,
                current_stage=current_stage,
                session=session,
            )

            if not path:
                return {"error": "Failed to generate career path"}

            return {
                "success": True,
                "path_id": path.id,
                "target_position": path.target_position,
                "path_type": path.path_type,
                "milestones": path.milestones,
                "learning_resources": path.learning_resources,
            }
    except Exception as exc:
        logger.error("create_career_path tool error | user_id={} | error={}", user_id, exc)
        return {"error": f"Career path generation failed: {exc}"}


@tool
async def create_growth_plan(
    user_id: int,
    growth_path_id: int,
    weekly_hours: int = 10,
    cycle_weeks: int = 12,
) -> dict:
    """Generate a growth plan based on a career path.

    Args:
        user_id: The user's ID.
        growth_path_id: The career path ID.
        weekly_hours: Available hours per week (default 10).
        cycle_weeks: Plan cycle in weeks (default 12).

    Returns:
        Dict with growth plan data or error message.
    """
    try:
        from app.core.matching.path_planner import generate_growth_plan
        from app.infrastructure.database import async_session_factory

        async with async_session_factory() as session:
            plan = await generate_growth_plan(
                user_id=user_id,
                growth_path_id=growth_path_id,
                weekly_hours=weekly_hours,
                cycle_weeks=cycle_weeks,
                session=session,
            )

            if not plan:
                return {"error": "Failed to generate growth plan"}

            return {
                "success": True,
                "plan_id": plan.id,
                "cycle_weeks": plan.cycle_weeks,
                "intensity": plan.intensity,
                "tasks": plan.tasks,
            }
    except Exception as exc:
        logger.error("create_growth_plan tool error | user_id={} | error={}", user_id, exc)
        return {"error": f"Growth plan generation failed: {exc}"}
