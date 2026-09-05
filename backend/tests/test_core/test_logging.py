import os


def test_loguru_logger_configured():
    from loguru import logger
    assert len(logger._core.handlers) >= 1


def test_langsmith_disabled_without_key():
    from app.infrastructure.langsmith import setup_langsmith
    setup_langsmith()
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"


def test_langsmith_enabled_with_key(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key-12345")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.infrastructure.langsmith import setup_langsmith
    setup_langsmith()
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGCHAIN_API_KEY") == "test-key-12345"
    assert os.environ.get("LANGCHAIN_PROJECT") == "career-planning-agent"

    get_settings.cache_clear()


def test_request_logging_middleware(client):
    resp = client.get("/health")
    assert resp.status_code == 200
