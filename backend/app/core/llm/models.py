"""LLM Provider 配置与 Adapter 工厂。

本模块是唯一直接接触 langchain-openai SDK 的地方（Adapter 隔离边界）。
gateway.py 只依赖 langchain 的 BaseChatModel 抽象接口，
若将来更换供应商或 SDK，仅需改动此处的 create_chat_model。
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, SecretStr

from app.config import Settings, get_settings


class LLMProviderConfig(BaseModel):
    """单个 LLM 供应商的配置。"""

    name: str
    api_key: SecretStr
    base_url: str
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    streaming: bool = True
    request_timeout: int = 60
    max_retries: int = 2


def build_provider_configs(settings: Settings | None = None) -> dict[str, LLMProviderConfig]:
    """从应用 Settings 构建各供应商配置。

    api_key 为空的供应商会被跳过（仅告警），避免网关持有只能返回 401 的模型。
    """
    settings = settings or get_settings()
    configs: dict[str, LLMProviderConfig] = {}

    candidates = [
        (
            "deepseek",
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        ),
        (
            "qwen",
            settings.qwen_api_key,
            settings.qwen_base_url,
            settings.qwen_model,
        ),
        (
            "longcat",
            settings.longcat_api_key,
            settings.longcat_base_url,
            settings.longcat_model,
        ),
    ]

    for name, api_key, base_url, model_name in candidates:
        if not api_key:
            logger.warning("LLM provider '{}' 未配置 api_key，已跳过", name)
            continue
        configs[name] = LLMProviderConfig(
            name=name,
            api_key=SecretStr(api_key),
            base_url=base_url,
            model_name=model_name,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=True,
            request_timeout=settings.llm_request_timeout,
        )

    return configs


def create_chat_model(config: LLMProviderConfig) -> BaseChatModel:
    """Adapter 工厂：把供应商配置转成 langchain BaseChatModel。

    构造过程不发起任何网络请求，可安全在导入/初始化阶段调用。
    """
    return ChatOpenAI(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        streaming=config.streaming,
        timeout=config.request_timeout,
        max_retries=config.max_retries,
    )


__all__ = [
    "LLMProviderConfig",
    "build_provider_configs",
    "create_chat_model",
]
