import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.job_agent.scheduler.schedule_adjuster import (
    calculate_adaptive_interval,
    calculate_change_rate,
    get_cold_start_interval,
    should_run_now,
)
from app.core.job_agent.scheduler.source_registry import _make_source_key


class TestCalculateAdaptiveInterval:
    def test_high_change_shortens_interval(self):
        result = calculate_adaptive_interval(
            current_interval=7.0,
            change_rate=0.5,
            consecutive_no_change=0,
        )
        assert result < 7.0  # Should shorten

    def test_low_change_lengthens_interval(self):
        result = calculate_adaptive_interval(
            current_interval=7.0,
            change_rate=0.0,
            consecutive_no_change=0,
        )
        assert result > 7.0  # Should lengthen

    def test_moderate_change_keeps_interval(self):
        result = calculate_adaptive_interval(
            current_interval=7.0,
            change_rate=0.1,
            consecutive_no_change=0,
        )
        assert result == 7.0

    def test_max_consecutive_no_change(self):
        result = calculate_adaptive_interval(
            current_interval=7.0,
            change_rate=0.0,
            consecutive_no_change=5,
            max_interval=60.0,
        )
        assert result == 60.0

    def test_clamps_to_min_interval(self):
        result = calculate_adaptive_interval(
            current_interval=1.5,
            change_rate=0.9,
            consecutive_no_change=0,
            min_interval=1.0,
        )
        assert result >= 1.0

    def test_clamps_to_max_interval(self):
        result = calculate_adaptive_interval(
            current_interval=50.0,
            change_rate=0.0,
            consecutive_no_change=0,
            max_interval=60.0,
        )
        assert result <= 60.0


class TestCalculateChangeRate:
    def test_first_run_with_items(self):
        assert calculate_change_rate(None, 10) == 1.0

    def test_first_run_empty(self):
        assert calculate_change_rate(None, 0) == 0.0

    def test_no_change(self):
        assert calculate_change_rate(100, 100) == 0.0

    def test_all_new(self):
        assert calculate_change_rate(0, 50) == 1.0

    def test_partial_change(self):
        rate = calculate_change_rate(100, 120)
        assert 0.19 < rate < 0.21  # ~20% increase


class TestShouldRunNow:
    def test_never_run(self):
        assert should_run_now(None, 7.0) is True

    def test_due_for_run(self):
        last_run = datetime.utcnow() - timedelta(days=8)
        assert should_run_now(last_run, 7.0) is True

    def test_not_yet_due(self):
        last_run = datetime.utcnow() - timedelta(days=3)
        assert should_run_now(last_run, 7.0) is False


class TestColdStartInterval:
    def test_default_is_7_days(self):
        assert get_cold_start_interval() == 7.0


class TestMakeSourceKey:
    def test_deterministic(self):
        key1 = _make_source_key("web", "https://example.com")
        key2 = _make_source_key("web", "https://example.com")
        assert key1 == key2

    def test_different_inputs_different_keys(self):
        key1 = _make_source_key("web", "https://a.com")
        key2 = _make_source_key("web", "https://b.com")
        assert key1 != key2


class TestSourceRegistry:
    @pytest.mark.asyncio
    async def test_register_source(self):
        from app.core.job_agent.scheduler.source_registry import SourceRegistry

        registry = SourceRegistry()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session

        # Mock execute() to return a result-like object
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.core.job_agent.scheduler.source_registry.async_session_factory",
            return_value=mock_session,
        ):
            result = await registry.register_source(
                source_name="Test Source",
                source_type="web",
                source_url="https://example.com",
            )

        assert result is not None
        assert mock_session.add.called

    @pytest.mark.asyncio
    async def test_save_report(self):
        from app.core.job_agent.scheduler.source_registry import SourceRegistry

        registry = SourceRegistry()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session

        with patch(
            "app.core.job_agent.scheduler.source_registry.async_session_factory",
            return_value=mock_session,
        ):
            result = await registry.save_report(
                industry="互联网/IT",
                title="Test Report",
                content="Report content here",
            )

        assert result is not None
        assert mock_session.add.called


class TestAdaptiveScheduler:
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        from app.core.job_agent.scheduler.adaptive_scheduler import AdaptiveScheduler

        scheduler = AdaptiveScheduler()
        scheduler.start()
        await asyncio.sleep(0.1)
        scheduler.shutdown()

    def test_get_job_info_empty(self):
        from app.core.job_agent.scheduler.adaptive_scheduler import AdaptiveScheduler

        scheduler = AdaptiveScheduler()
        info = scheduler.get_job_info()
        assert info == []
