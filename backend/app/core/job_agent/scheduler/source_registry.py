from __future__ import annotations

import hashlib
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from app.domain.models.scheduler import IndustryReport, JobUpdateSchedule
from app.infrastructure.database import async_session_factory


def _make_source_key(source_type: str, identifier: str) -> str:
    """Generate a unique source key from type and identifier."""
    raw = f"{source_type}:{identifier}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


class SourceRegistry:
    """Registry for tracking data sources and their update status.

    Provides CRUD operations for JobUpdateSchedule entries and
    IndustryReport storage.
    """

    async def register_source(
        self,
        source_name: str,
        source_type: str = "web",
        source_url: str | None = None,
        industry: str | None = None,
        keywords: str | None = None,
        interval_days: float = 7.0,
        min_interval_days: float = 1.0,
        max_interval_days: float = 60.0,
    ) -> JobUpdateSchedule:
        """Register a new data source or update existing one."""
        source_key = _make_source_key(source_type, source_url or source_name)

        async with async_session_factory() as session:
            try:
                result = await session.execute(
                    select(JobUpdateSchedule).where(JobUpdateSchedule.source_key == source_key)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.source_name = source_name
                    existing.source_url = source_url
                    existing.industry = industry
                    existing.keywords = keywords
                    existing.interval_days = interval_days
                    existing.min_interval_days = min_interval_days
                    existing.max_interval_days = max_interval_days
                    await session.commit()
                    await session.refresh(existing)
                    logger.info("Source registry: updated source | key={}", source_key)
                    return existing

                schedule = JobUpdateSchedule(
                    source_key=source_key,
                    source_name=source_name,
                    source_type=source_type,
                    source_url=source_url,
                    industry=industry,
                    keywords=keywords,
                    interval_days=interval_days,
                    min_interval_days=min_interval_days,
                    max_interval_days=max_interval_days,
                )
                session.add(schedule)
                await session.commit()
                await session.refresh(schedule)
                logger.info("Source registry: registered source | key={} | name={}", source_key, source_name)
                return schedule
            except Exception:
                await session.rollback()
                raise

    async def get_source(self, source_key: str) -> JobUpdateSchedule | None:
        """Get a source by its key."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobUpdateSchedule).where(JobUpdateSchedule.source_key == source_key)
            )
            return result.scalar_one_or_none()

    async def list_sources(self, active_only: bool = True) -> list[JobUpdateSchedule]:
        """List all registered sources."""
        async with async_session_factory() as session:
            stmt = select(JobUpdateSchedule)
            if active_only:
                stmt = stmt.where(JobUpdateSchedule.is_active == True)  # noqa: E712
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_after_run(
        self,
        source_key: str,
        item_count: int,
        change_rate: float,
    ) -> None:
        """Update source statistics after a crawl run."""
        async with async_session_factory() as session:
            try:
                result = await session.execute(
                    select(JobUpdateSchedule).where(JobUpdateSchedule.source_key == source_key)
                )
                schedule = result.scalar_one_or_none()
                if not schedule:
                    return

                schedule.last_run_at = datetime.utcnow()
                schedule.last_item_count = item_count
                schedule.last_change_rate = change_rate

                if change_rate == 0:
                    schedule.consecutive_no_change += 1
                else:
                    schedule.consecutive_no_change = 0

                await session.commit()
                logger.info("Source registry: updated after run | key={} | items={} | change={}",
                            source_key, item_count, change_rate)
            except Exception:
                await session.rollback()
                raise

    async def save_report(
        self,
        industry: str,
        title: str,
        content: str,
        sections: dict | None = None,
        source_urls: list[str] | None = None,
        keywords: str | None = None,
        item_count: int | None = None,
        is_ai_enriched: bool = True,
        valid_until: datetime | None = None,
    ) -> IndustryReport:
        """Save a generated industry report."""
        content_hash = hashlib.md5(content.encode()).hexdigest()

        async with async_session_factory() as session:
            try:
                report = IndustryReport(
                    industry=industry,
                    title=title,
                    content=content,
                    sections=sections,
                    source_urls=source_urls,
                    keywords=keywords,
                    item_count=item_count,
                    is_ai_enriched=is_ai_enriched,
                    report_hash=content_hash,
                    valid_until=valid_until,
                )
                session.add(report)
                await session.commit()
                await session.refresh(report)
                logger.info("Source registry: saved report | industry={} | title={!r:.60}",
                            industry, title)
                return report
            except Exception:
                await session.rollback()
                raise

    async def get_latest_report(self, industry: str) -> IndustryReport | None:
        """Get the most recent report for an industry."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(IndustryReport)
                .where(IndustryReport.industry == industry)
                .order_by(IndustryReport.generated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()


async def get_source_registry() -> SourceRegistry:
    """Factory for SourceRegistry."""
    return SourceRegistry()
