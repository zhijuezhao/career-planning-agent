"""Tests for config.py — Settings loading and defaults."""

import os
from unittest.mock import patch

from app.config import Settings, get_settings


class TestSettingsDefaults:
    def test_default_app_name(self):
        settings = Settings()
        assert settings.app_name == "career-planning-agent"

    def test_default_app_env(self):
        settings = Settings()
        assert settings.app_env == "development"

    def test_default_app_port(self):
        settings = Settings()
        assert settings.app_port == 8000

    def test_default_database_url(self):
        settings = Settings()
        assert "postgresql" in settings.database_url

    def test_default_redis_url(self):
        settings = Settings()
        assert "redis" in settings.redis_url

    def test_default_jwt_algorithm(self):
        settings = Settings()
        assert settings.jwt_algorithm == "HS256"

    def test_default_jwt_expiry(self):
        settings = Settings()
        assert settings.jwt_access_token_expire_minutes == 1440

    def test_default_upload_dir(self):
        settings = Settings()
        assert settings.upload_dir == "./uploads"

    def test_default_max_upload_size_mb(self):
        settings = Settings()
        assert settings.max_upload_size_mb == 10

    def test_default_resume_max_text_chars(self):
        settings = Settings()
        assert settings.resume_max_text_chars == 15000


class TestSettingsProperties:
    def test_is_development_true(self):
        settings = Settings(app_env="development")
        assert settings.is_development is True

    def test_is_development_false(self):
        settings = Settings(app_env="production")
        assert settings.is_development is False

    def test_max_upload_size_bytes(self):
        settings = Settings(max_upload_size_mb=10)
        assert settings.max_upload_size_bytes == 10 * 1024 * 1024

    def test_max_upload_size_bytes_custom(self):
        settings = Settings(max_upload_size_mb=5)
        assert settings.max_upload_size_bytes == 5 * 1024 * 1024


class TestSettingsFromEnv:
    def test_env_override_app_name(self):
        with patch.dict(os.environ, {"APP_NAME": "custom-app"}):
            settings = Settings()
            assert settings.app_name == "custom-app"

    def test_env_override_app_port(self):
        with patch.dict(os.environ, {"APP_PORT": "9000"}):
            settings = Settings()
            assert settings.app_port == 9000

    def test_env_override_database_url(self):
        custom_url = "postgresql+asyncpg://user:pass@host:5432/db"
        with patch.dict(os.environ, {"DATABASE_URL": custom_url}):
            settings = Settings()
            assert settings.database_url == custom_url

    def test_env_override_jwt_secret(self):
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret"}):
            settings = Settings()
            assert settings.jwt_secret_key == "test-secret"

    def test_env_override_upload_dir(self):
        with patch.dict(os.environ, {"UPLOAD_DIR": "/tmp/uploads"}):
            settings = Settings()
            assert settings.upload_dir == "/tmp/uploads"


class TestGetSettings:
    def test_get_settings_returns_instance(self):
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_cached(self):
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_get_settings_cache_clear(self):
        get_settings.cache_clear()
        settings1 = get_settings()
        get_settings.cache_clear()
        settings2 = get_settings()
        assert settings1 is not settings2


class TestLLMSettings:
    def test_default_deepseek_model(self):
        settings = Settings(_env_file=None)
        assert settings.deepseek_model == "deepseek-chat"

    def test_default_qwen_model(self):
        settings = Settings(_env_file=None)
        assert settings.qwen_model == "qwen-plus"

    def test_default_embedding_model(self):
        settings = Settings(_env_file=None)
        assert "Qwen3" in settings.siliconflow_embedding_model

    def test_default_llm_fallback_order(self):
        settings = Settings(_env_file=None)
        assert settings.llm_fallback_order == "deepseek,qwen"

    def test_default_llm_temperature(self):
        settings = Settings(_env_file=None)
        assert settings.llm_temperature == 0.7

    def test_default_llm_max_tokens(self):
        settings = Settings(_env_file=None)
        assert settings.llm_max_tokens == 4096
