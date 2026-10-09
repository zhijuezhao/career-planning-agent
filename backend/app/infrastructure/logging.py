import sys
from pathlib import Path

from loguru import logger

from app.config import get_settings


def setup_logging():
    settings = get_settings()
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # `LOG_LEVEL` 留空 = 历史行为（开发 DEBUG / 生产 INFO）；
    # `LOG_FILE` 只取目录，文件名仍按天轮转（2026-10-09 审计：原先 LOG_LEVEL 配了不生效）。
    level = settings.log_level.strip().upper() or ("DEBUG" if settings.is_development else "INFO")
    log_dir = Path(settings.log_file).parent

    logger.add(
        sys.stderr,
        format=log_format,
        level=level,
        colorize=True,
    )

    logger.add(
        f"{log_dir}/app_{{time:YYYY-MM-DD}}.log",
        format=log_format,
        level="INFO",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
    )

    if not settings.is_development:
        logger.add(
            f"{log_dir}/error_{{time:YYYY-MM-DD}}.log",
            format=log_format,
            level="ERROR",
            rotation="00:00",
            retention="90 days",
            compression="gz",
            encoding="utf-8",
        )

    logger.info("Logging initialized | env={} | debug={}", settings.app_env, settings.is_development)
