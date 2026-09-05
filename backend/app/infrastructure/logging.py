import sys

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

    logger.add(
        sys.stderr,
        format=log_format,
        level="DEBUG" if settings.is_development else "INFO",
        colorize=True,
    )

    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="INFO",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
    )

    if not settings.is_development:
        logger.add(
            "logs/error_{time:YYYY-MM-DD}.log",
            format=log_format,
            level="ERROR",
            rotation="00:00",
            retention="90 days",
            compression="gz",
            encoding="utf-8",
        )

    logger.info("Logging initialized | env={} | debug={}", settings.app_env, settings.is_development)
