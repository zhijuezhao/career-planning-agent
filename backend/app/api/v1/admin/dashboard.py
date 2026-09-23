from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.import_job import DataImportJob
from app.domain.models.job import JobProfile, JobRawData
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.report import ChatSession
from app.domain.models.report_record import ReportRecord
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    DashboardOverview,
    ImportOverview,
    JobCategoryStat,
    QualityDistribution,
    SnapshotStats,
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

    # Total chat sessions
    chat_count = (await db.execute(select(func.count()).select_from(ChatSession))).scalar() or 0

    # 已匹配的画像快照数（匹配明细不再落表，matched_at 为完成标记）
    matched_count = (
        await db.execute(
            select(func.count())
            .select_from(ProfileSnapshot)
            .where(ProfileSnapshot.matched_at.isnot(None))
        )
    ).scalar() or 0

    # 报告记录数（原 CareerReport 表已删除，改为 report_records）
    report_count = (
        await db.execute(select(func.count()).select_from(ReportRecord))
    ).scalar() or 0

    return DashboardOverview(
        total_users=user_count,
        total_resumes=resume_count,
        total_job_profiles=job_count,
        total_matches=matched_count,
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
            select(func.count()).select_from(JobRawData).where(JobRawData.is_active.is_(True))
        )
    ).scalar() or 0

    inactive_count = (
        await db.execute(
            select(func.count()).select_from(JobRawData).where(JobRawData.is_active.is_(False))
        )
    ).scalar() or 0

    return [
        QualityDistribution(grade="活跃", count=active_count),
        QualityDistribution(grade="非活跃", count=inactive_count),
    ]


@router.get("/snapshot-stats", response_model=SnapshotStats)
async def snapshot_stats(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """画像快照 / 匹配进度统计（替代原 /match-stats，D8）。"""
    total = (
        await db.execute(select(func.count()).select_from(ProfileSnapshot))
    ).scalar() or 0
    matched = (
        await db.execute(
            select(func.count())
            .select_from(ProfileSnapshot)
            .where(ProfileSnapshot.matched_at.isnot(None))
        )
    ).scalar() or 0
    return SnapshotStats(
        total_snapshots=total,
        matched_snapshots=matched,
        pending_snapshots=total - matched,
    )


@router.get("/import-overview", response_model=ImportOverview)
async def import_overview(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """导入任务总览（P1-6）：按状态分组计数 + 行数求和 + 最近一次导入时间。"""
    status_rows = (
        await db.execute(
            select(DataImportJob.status, func.count()).group_by(DataImportJob.status)
        )
    ).all()
    counts = {status: count for status, count in status_rows}

    total_rows, success_rows, error_rows, last_at = (
        await db.execute(
            select(
                func.coalesce(func.sum(DataImportJob.total_rows), 0),
                func.coalesce(func.sum(DataImportJob.success_count), 0),
                func.coalesce(func.sum(DataImportJob.error_count), 0),
                func.max(DataImportJob.created_at),
            )
        )
    ).one()

    return ImportOverview(
        total_jobs=sum(counts.values()),
        pending=counts.get("pending", 0),
        processing=counts.get("processing", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        total_rows=int(total_rows),
        success_rows=int(success_rows),
        error_rows=int(error_rows),
        last_import_at=last_at,
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

    # Check scheduler：读应用启动时挂载的实例（与 system.py 同口径），
    # 不要现场 new —— 旧实现既漏跑依赖注入、又不存在公开的 running 属性，恒返回 unknown。
    from app.main import app

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        scheduler_status = "not_initialized"
    else:
        inner = getattr(scheduler, "_scheduler", None)
        scheduler_status = "running" if getattr(inner, "running", False) else "stopped"

    # Check LLM gateway
    from app.core.llm.gateway import get_llm_gateway
    gateway = get_llm_gateway()
    llm_status = "healthy" if gateway.list_models() else "no_models"

    return SystemHealth(
        database=db_status,
        scheduler=scheduler_status,
        llm_gateway=llm_status,
    )
