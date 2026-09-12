"""Tests for core/llm/models.py — LLM provider config and adapter factory."""

import pytest
from pydantic import SecretStr

from app.core.llm.models import (
    LLMProviderConfig,
    build_provider_configs,
    create_chat_model,
)
from app.config import Settings


class TestLLMProviderConfig:
    def test_create_config_with_defaults(self):
        config = LLMProviderConfig(
            name="test",
            api_key=SecretStr("test-key"),
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )
        assert config.name == "test"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.streaming is True
        assert config.request_timeout == 60
        assert config.max_retries == 2

    def test_create_config_with_custom_values(self):
        config = LLMProviderConfig(
            name="custom",
            api_key=SecretStr("key"),
            base_url="https://api.custom.com/v1",
            model_name="custom-model",
            temperature=0.5,
            max_tokens=2048,
            streaming=False,
            request_timeout=30,
            max_retries=3,
        )
        assert config.temperature == 0.5
        assert config.max_tokens == 2048
        assert config.streaming is False
        assert config.request_timeout == 30
        assert config.max_retries == 3

    def test_api_key_is_secret(self):
        config = LLMProviderConfig(
            name="test",
            api_key=SecretStr("secret-key"),
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )
        assert str(config.api_key) == "**********"
        assert config.api_key.get_secret_value() == "secret-key"


class TestBuildProviderConfigs:
    def test_empty_configs_when_no_api_keys(self):
        settings = Settings(
            deepseek_api_key="",
            qwen_api_key="",
            longcat_api_key="",
        )
        configs = build_provider_configs(settings)
        assert configs == {}

    def test_deepseek_config_built_when_api_key_set(self):
        settings = Settings(
            deepseek_api_key="ds-key",
            qwen_api_key="",
            longcat_api_key="",
        )
        configs = build_provider_configs(settings)
        assert "deepseek" in configs
        assert configs["deepseek"].name == "deepseek"
        assert configs["deepseek"].model_name == settings.deepseek_model

    def test_qwen_config_built_when_api_key_set(self):
        settings = Settings(
            deepseek_api_key="",
            qwen_api_key="qwen-key",
            longcat_api_key="",
        )
        configs = build_provider_configs(settings)
        assert "qwen" in configs
        assert configs["qwen"].name == "qwen"

    def test_longcat_config_built_when_api_key_set(self):
        settings = Settings(
            deepseek_api_key="",
            qwen_api_key="",
            longcat_api_key="lc-key",
        )
        configs = build_provider_configs(settings)
        assert "longcat" in configs
        assert configs["longcat"].name == "longcat"

    def test_multiple_providers_built(self):
        settings = Settings(
            deepseek_api_key="ds-key",
            qwen_api_key="qwen-key",
            longcat_api_key="lc-key",
        )
        configs = build_provider_configs(settings)
        assert len(configs) == 3
        assert "deepseek" in configs
        assert "qwen" in configs
        assert "longcat" in configs

    def test_skips_empty_api_key_with_warning(self, caplog):
        settings = Settings(
            deepseek_api_key="ds-key",
            qwen_api_key="",
            longcat_api_key="lc-key",
        )
        configs = build_provider_configs(settings)
        assert "qwen" not in configs
        assert len(configs) == 2

    def test_uses_settings_temperature_and_max_tokens(self):
        settings = Settings(
            deepseek_api_key="ds-key",
            qwen_api_key="",
            longcat_api_key="",
            llm_temperature=0.9,
            llm_max_tokens=8192,
        )
        configs = build_provider_configs(settings)
        assert configs["deepseek"].temperature == 0.9
        assert configs["deepseek"].max_tokens == 8192


class TestCreateChatModel:
    def test_creates_chat_model_from_config(self):
        config = LLMProviderConfig(
            name="test",
            api_key=SecretStr("test-key"),
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )
        model = create_chat_model(config)
        assert model is not None
        assert model.model_name == "test-model"

    def test_model_has_correct_temperature(self):
        config = LLMProviderConfig(
            name="test",
            api_key=SecretStr("test-key"),
            base_url="https://api.test.com/v1",
            model_name="test-model",
            temperature=0.5,
        )
        model = create_chat_model(config)
        assert model.temperature == 0.5

    def test_model_has_correct_max_tokens(self):
        config = LLMProviderConfig(
            name="test",
            api_key=SecretStr("test-key"),
            base_url="https://api.test.com/v1",
            model_name="test-model",
            max_tokens=2048,
        )
        model = create_chat_model(config)
        assert model.max_tokens == 2048
