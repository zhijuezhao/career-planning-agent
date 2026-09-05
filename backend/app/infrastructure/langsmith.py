import os

from loguru import logger

from app.config import get_settings


def setup_langsmith():
    settings = get_settings()

    if not settings.langchain_api_key or settings.langchain_api_key == "your-langsmith-api-key":
        logger.warning("LangSmith API key not configured, tracing disabled")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

    logger.info(
        "LangSmith tracing enabled | project={} | endpoint={}",
        settings.langchain_project,
        "https://api.smith.langchain.com",
    )
