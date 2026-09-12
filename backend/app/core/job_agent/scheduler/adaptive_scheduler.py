from __future__ import annotations

from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from app.core.job_agent.scheduler.schedule_adjuster import (
    calculate_adaptive_interval,
    calculate_change_rate,
    get_cold_start_interval,
)
from app.core.job_agent.scheduler.source_registry import SourceRegistry, get_source_registry


class AdaptiveScheduler:
    """Adaptive scheduler for job data collection.

    Uses APScheduler AsyncIOScheduler to manage periodic crawl jobs.
    Supports manual interval adjustment and adaptive frequency based
    on change rate.
    """

    def __init__(self, registry: SourceRegistry | None = None):
        self._scheduler = AsyncIOScheduler()
        self._registry = registry or get_source_registry()
        self._jobs: dict[str, str] = {}  # source_key -> job_id

    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Adaptive scheduler started")

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Adaptive scheduler shutdown")

    async def register_and_schedule(
        self,
        source_name: str,
        task_func: Callable[..., Awaitable[Any]],
        source_type: str = "web",
        source_url: str | None = None,
        industry: str | None = None,
        keywords: str | None = None,
        interval_days: float | None = None,
        **task_kwargs: Any,
    ) -> str:
        """Register a source and schedule its crawl task.

        Args:
            source_name: Human-readable name for the source.
            task_func: Async function to call on each run.
            source_type: Type of source (web, api, file).
            source_url: URL of the source.
            industry: Industry category.
            keywords: Search keywords.
            interval_days: Initial interval (default: cold start 7 days).
            **task_kwargs: Additional kwargs passed to task_func.

        Returns:
            The job_id of the scheduled job.
        """
        interval = interval_days or get_cold_start_interval()

        # Register in database
        schedule = await self._registry.register_source(
            source_name=source_name,
            source_type=source_type,
            source_url=source_url,
            industry=industry,
            keywords=keywords,
            interval_days=interval,
        )

        # Create APScheduler job
        job = self._scheduler.add_job(
            func=self._wrap_task,
            trigger=IntervalTrigger(days=interval),
            args=[schedule.source_key, task_func],
            kwargs=task_kwargs,
            id=schedule.source_key,
            name=source_name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self._jobs[schedule.source_key] = job.id
        logger.info("Adaptive scheduler: scheduled | source={} | interval={}days | job_id={}",
                    source_name, interval, job.id)
        return job.id

    async def reschedule(self, source_key: str, new_interval_days: float) -> bool:
        """Manually reschedule a job with a new interval.

        Args:
            source_key: The source key to reschedule.
            new_interval_days: New interval in days.

        Returns:
            True if rescheduled successfully.
        """
        job_id = self._jobs.get(source_key)
        if not job_id:
            logger.warning("Adaptive scheduler: no job found for source_key={}", source_key)
            return False

        try:
            self._scheduler.reschedule_job(
                job_id,
                trigger=IntervalTrigger(days=new_interval_days),
            )
            logger.info("Adaptive scheduler: rescheduled | key={} -> {}days",
                        source_key, new_interval_days)
            return True
        except Exception as exc:
            logger.warning("Adaptive scheduler: reschedule failed | key={} | error={}",
                           source_key, exc)
            return False

    async def pause_source(self, source_key: str) -> bool:
        """Pause a scheduled source."""
        job_id = self._jobs.get(source_key)
        if not job_id:
            return False
        try:
            self._scheduler.pause_job(job_id)
            logger.info("Adaptive scheduler: paused | key={}", source_key)
            return True
        except Exception as exc:
            logger.warning("Adaptive scheduler: pause failed | key={} | error={}", source_key, exc)
            return False

    async def resume_source(self, source_key: str) -> bool:
        """Resume a paused source."""
        job_id = self._jobs.get(source_key)
        if not job_id:
            return False
        try:
            self._scheduler.resume_job(job_id)
            logger.info("Adaptive scheduler: resumed | key={}", source_key)
            return True
        except Exception as exc:
            logger.warning("Adaptive scheduler: resume failed | key={} | error={}", source_key, exc)
            return False

    def get_job_info(self) -> list[dict[str, Any]]:
        """Get information about all scheduled jobs."""
        info = []
        for job in self._scheduler.get_jobs():
            info.append({
                "job_id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return info

    async def _wrap_task(
        self,
        source_key: str,
        task_func: Callable[..., Awaitable[Any]],
        **kwargs: Any,
    ) -> None:
        """Wrapper that runs the task and adjusts schedule based on results."""
        logger.info("Adaptive scheduler: running task | key={}", source_key)

        try:
            result = await task_func(**kwargs)
            new_count = result.get("item_count", 0) if isinstance(result, dict) else 0
        except Exception as exc:
            logger.warning("Adaptive scheduler: task failed | key={} | error={}", source_key, exc)
            new_count = 0

        # Get current schedule state
        schedule = await self._registry.get_source(source_key)
        if not schedule:
            return

        # Calculate change rate
        change_rate = calculate_change_rate(schedule.last_item_count, new_count)

        # Update registry
        await self._registry.update_after_run(source_key, new_count, change_rate)

        # Calculate new interval
        new_interval = calculate_adaptive_interval(
            current_interval=schedule.interval_days,
            change_rate=change_rate,
            consecutive_no_change=schedule.consecutive_no_change,
            min_interval=schedule.min_interval_days,
            max_interval=schedule.max_interval_days,
        )

        # Reschedule if interval changed significantly
        if abs(new_interval - schedule.interval_days) > 0.1:
            await self.reschedule(source_key, new_interval)


async def get_adaptive_scheduler() -> AdaptiveScheduler:
    """Factory for AdaptiveScheduler."""
    return AdaptiveScheduler()
