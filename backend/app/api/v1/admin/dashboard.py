from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.job import JobProfile, JobRawData
from app.domain.models.report import CareerReport, ChatSession, JobMatch, UserFeedback
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    DashboardOverview,
    JobCategoryStat,
    MatchStats,
    QualityDistribution,
    SystemHealth,
    UserGrowthStat,
)

router = APIRouter()


@router.get("/health")
async def admin_health(current_user: User = Depends(require_admin)):
    """Admin health check endpoint."""
    return {"status": "ok", "admin": current_user.username}


@router.get("/overview", response_model=DashboardOverview)
async def dashboard_overview(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard overview statistics."""
    # Total users
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    # Total resumes (from Resume model)
    from app.domain.models.resume import Resume
    resume_count = (await db.execute(select(func.count()).select_from(Resume))).scalar() or 0

    # Total job profiles
    job_count = (await db.execute(select(func.count()).select_from(JobProfile))).scalar() or 0

    # Total matches
    match_count = (await db.execute(select(func.count()).select_from(JobMatch))).scalar() or 0

    # Total reports
    report_count = (await db.execute(select(func.count()).select_from(CareerReport))).scalar() or 0

    # Total chat sessions
    chat_count = (await db.execute(select(func.count()).select_from(ChatSession))).scalar() or 0

    return DashboardOverview(
        total_users=user_count,
        total_resumes=resume_count,
        total_job_profiles=job_count,
        total_matches=match_count,
        total_reports=report_count,
        total_chat_sessions=chat_count,
    )


@router.get("/user-growth", response_model=list[UserGrowthStat])
async def user_growth(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get user growth statistics (last 30 days)."""
    from datetime import datetime, timedelta

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    stmt = (
        select(
            func.date(User.created_at).label("date"),
            func.count().label("count"),
        )
        .where(User.created_at >= thirty_days_ago)
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [UserGrowthStat(date=str(row.date), count=row.count) for row in rows]


@router.get("/job-categories", response_model=list[JobCategoryStat])
async def job_categories(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get job profile distribution by industry."""
    stmt = (
        select(
            JobProfile.industry,
            func.count().label("count"),
        )
        .where(JobProfile.industry.isnot(None))
        .group_by(JobProfile.industry)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [JobCategoryStat(category=row.industry or "未知", count=row.count) for row in rows]


@router.get("/quality-distribution", response_model=list[QualityDistribution])
async def quality_distribution(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get job data quality distribution."""
    # Count active vs inactive raw data
    active_count = (
        await db.execute(
            select(func.count()).select_from(JobRawData).where(JobRawData.is_active == True)
        )
    ).scalar() or 0

    inactive_count = (
        await db.execute(
            select(func.count()).select_from(JobRawData).where(JobRawData.is_active == False)
        )
    ).scalar() or 0

    return [
        QualityDistribution(grade="活跃", count=active_count),
        QualityDistribution(grade="非活跃", count=inactive_count),
    ]


@router.get("/match-stats", response_model=MatchStats)
async def match_stats(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get matching statistics."""
    # Average match score
    avg_score = (
        await db.execute(
            select(func.avg(JobMatch.match_score)).where(JobMatch.match_score.isnot(None))
        )
    ).scalar() or 0.0

    # Total matches
    total_matches = (await db.execute(select(func.count()).select_from(JobMatch))).scalar() or 0

    # Feedback count
    feedback_count = (await db.execute(select(func.count()).select_from(UserFeedback))).scalar() or 0

    return MatchStats(
        avg_score=round(float(avg_score), 4),
        total_matches=total_matches,
        feedback_count=feedback_count,
    )


@router.get("/system-health", response_model=SystemHealth)
async def system_health(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get system health status."""
    # Check database
    try:
        await db.execute(select(1))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    # Check scheduler
    try:
        from app.core.job_agent.scheduler.adaptive_scheduler import AdaptiveScheduler
        scheduler = AdaptiveScheduler()
        scheduler_status = "running" if scheduler.running else "stopped"
    except Exception:
        scheduler_status = "unknown"

    # Check LLM gateway
    from app.core.llm.gateway import get_llm_gateway
    gateway = get_llm_gateway()
    llm_status = "healthy" if gateway.list_models() else "no_models"

    return SystemHealth(
        database=db_status,
        scheduler=scheduler_status,
        llm_gateway=llm_status,
    )
