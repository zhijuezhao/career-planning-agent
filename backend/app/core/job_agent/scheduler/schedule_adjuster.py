from __future__ import annotations

from datetime import datetime

from loguru import logger

# Default configuration for adaptive scheduling
DEFAULT_MIN_INTERVAL_DAYS = 1.0
DEFAULT_MAX_INTERVAL_DAYS = 60.0
DEFAULT_COLD_START_INTERVAL_DAYS = 7.0

# Change rate thresholds
HIGH_CHANGE_THRESHOLD = 0.3    # >30% change = high activity
LOW_CHANGE_THRESHOLD = 0.05     # <5% change = low activity

# Adjustment factors
SHORTEN_FACTOR = 0.6            # Reduce interval by 40% on high change
LENGTHEN_FACTOR = 1.5           # Increase interval by 50% on low change
MAX_CONSECUTIVE_NO_CHANGE = 5   # After 5 no-change runs, max out interval


def calculate_adaptive_interval(
    current_interval: float,
    change_rate: float,
    consecutive_no_change: int,
    min_interval: float = DEFAULT_MIN_INTERVAL_DAYS,
    max_interval: float = DEFAULT_MAX_INTERVAL_DAYS,
) -> float:
    """Calculate the next update interval based on change rate.

    Args:
        current_interval: Current interval in days.
        change_rate: Rate of change (0.0 to 1.0+), where 0 = no change.
        consecutive_no_change: Number of consecutive runs with no change.
        min_interval: Minimum allowed interval in days.
        max_interval: Maximum allowed interval in days.

    Returns:
        New interval in days, clamped to [min_interval, max_interval].
    """
    if consecutive_no_change >= MAX_CONSECUTIVE_NO_CHANGE:
        # Max out interval after many no-change runs
        new_interval = max_interval
        logger.info("Schedule adjuster: max consecutive no-change ({}), setting to {} days",
                    consecutive_no_change, new_interval)
    elif change_rate >= HIGH_CHANGE_THRESHOLD:
        # High activity: shorten interval to check more frequently
        new_interval = current_interval * SHORTEN_FACTOR
        logger.info("Schedule adjuster: high change rate ({:.2%}), shortening {:.1f}d -> {:.1f}d",
                    change_rate, current_interval, new_interval)
    elif change_rate <= LOW_CHANGE_THRESHOLD:
        # Low activity: lengthen interval to save resources
        new_interval = current_interval * LENGTHEN_FACTOR
        logger.info("Schedule adjuster: low change rate ({:.2%}), lengthening {:.1f}d -> {:.1f}d",
                    change_rate, current_interval, new_interval)
    else:
        # Moderate change: keep current interval
        new_interval = current_interval
        logger.info("Schedule adjuster: moderate change rate ({:.2%}), keeping {:.1f}d",
                    change_rate, new_interval)

    # Clamp to allowed range
    clamped = max(min_interval, min(max_interval, new_interval))
    return round(clamped, 2)


def calculate_change_rate(old_count: int | None, new_count: int) -> float:
    """Calculate the rate of change between two item counts.

    Args:
        old_count: Previous item count (None if first run).
        new_count: Current item count.

    Returns:
        Change rate as a float (0.0 = no change, 1.0 = all new).
    """
    if old_count is None or old_count == 0:
        # First run or empty before: treat as 100% change if new items exist
        return 1.0 if new_count > 0 else 0.0

    if new_count == 0:
        return 0.0

    # Calculate relative change
    added = max(0, new_count - old_count)
    rate = added / old_count
    return round(min(rate, 2.0), 4)  # Cap at 200% to avoid extreme values


def get_cold_start_interval() -> float:
    """Get the default interval for new sources (cold start)."""
    return DEFAULT_COLD_START_INTERVAL_DAYS


def should_run_now(
    last_run_at: datetime | None,
    interval_days: float,
    current_time: datetime | None = None,
) -> bool:
    """Check if a source should be run now based on its schedule.

    Args:
        last_run_at: When the source was last run (None if never).
        interval_days: Configured interval in days.
        current_time: Current time (defaults to utcnow).

    Returns:
        True if the source should be run now.
    """
    if last_run_at is None:
        return True

    if current_time is None:
        current_time = datetime.utcnow()

    elapsed = (current_time - last_run_at).total_seconds()
    threshold = interval_days * 24 * 3600
    return elapsed >= threshold
