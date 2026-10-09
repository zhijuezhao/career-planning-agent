"""Tests for config.py — Settings loading and defaults."""

import os
from unittest.mock import patch

import pytest
from app.config import Settings, get_settings
from pydantic import ValidationError


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
        # production 必须有强随机 JWT 密钥，否则 Settings 拒绝构造（见 TestProductionJwtGuard）
        settings = Settings(app_env="production", jwt_secret_key="a" * 64)
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


class TestProductionJwtGuard:
    """生产环境弱/占位 JWT 密钥必须 fail closed（2026-10-09 安全审计 P1-4）。"""

    def test_production_with_placeholder_secret_rejected(self):
        with pytest.raises(ValidationError):
            Settings(
                app_env="production",
                jwt_secret_key="change-me-to-a-random-secret-key-in-production",
            )

    def test_production_with_uppercase_placeholder_rejected(self):
        with pytest.raises(ValidationError):
            Settings(
                app_env="production",
                jwt_secret_key="CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32",
            )

    def test_production_with_short_secret_rejected(self):
        with pytest.raises(ValidationError):
            Settings(app_env="production", jwt_secret_key="short-secret")

    def test_production_with_strong_secret_ok(self):
        secret = "b" * 64
        settings = Settings(app_env="production", jwt_secret_key=secret)
        assert settings.jwt_secret_key == secret

    def test_development_still_allows_placeholder(self):
        settings = Settings(app_env="development")
        assert settings.jwt_secret_key


class TestCorsOrigins:
    """`CORS_ORIGINS` 必须真正生效，且不能挤掉本地开发来源（审计 M-6）。"""

    def test_defaults_include_dev_frontends(self):
        origins = Settings(_env_file=None, cors_origins="").cors_origin_list
        assert "http://localhost:5173" in origins

    def test_configured_origins_appended_and_deduped(self):
        origins = Settings(
            _env_file=None,
            cors_origins="https://a.com, http://localhost:5173",
        ).cors_origin_list
        assert "https://a.com" in origins
        assert origins.count("http://localhost:5173") == 1
        assert "" not in origins


class TestDeploymentVarsAccepted:
    """docker-compose / .env.production.example 注入的变量必须能被 Settings 接受。

    否则整份 `.env` 会触发 pydantic-settings 的 `extra_forbidden`，
    后端**直接启动失败**（2026-10-09 安全审计发现的实际故障）。
    """

    def test_compose_only_vars_do_not_break_settings(self):
        settings = Settings(
            _env_file=None,
            postgres_db="career_planning",
            postgres_user="postgres",
            postgres_password="CHANGE_ME",
            redis_password="CHANGE_ME",
            dashscope_api_key="sk-ws-placeholder",
            qwen_embedding_model="qwen3-vl-embedding",
            cors_origins="https://yourdomain.com",
            log_level="INFO",
            log_file="./logs/app.log",
            allowed_hosts="yourdomain.com",
        )
        assert settings.postgres_db == "career_planning"
        assert settings.log_level == "INFO"
