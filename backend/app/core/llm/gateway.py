"""LLM 网关：多模型热切换 + Adapter 隔离 + fallback。

上层（简历解析、画像构建、Agent、SSE 对话）统一通过 get_llm_gateway() 调用，
不直接接触 langchain SDK。LangSmith 追踪由环境变量全局启用，无需在此处理。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from loguru import logger

from app.config import get_settings
from app.core.llm.models import (
    LLMProviderConfig,
    build_provider_configs,
    create_chat_model,
)


class LLMGatewayError(RuntimeError):
    """网关基础异常。"""


class AllProvidersFailedError(LLMGatewayError):
    """fallback 链上所有供应商均失败，携带每个供应商的失败原因。"""

    def __init__(self, errors: dict[str, Exception]):
        self.errors = errors
        names = ", ".join(errors.keys())
        super().__init__(f"All LLM providers failed: {names}")


class UnknownModelError(LLMGatewayError):
    """引用了未注册的模型名（快速失败，便于发现管理端配置错误）。"""


class LLMGateway:
    """多模型网关，支持运行时热切换与失败自动 fallback。"""

    def __init__(
        self,
        provider_configs: dict[str, LLMProviderConfig] | None = None,
        models: dict[str, BaseChatModel] | None = None,
        default_model: str | None = None,
        fallback_order: list[str] | None = None,
    ):
        settings = get_settings()

        # 模型注册表：优先使用注入的 models（测试用），否则由配置构建
        if models is not None:
            self._models: dict[str, BaseChatModel] = dict(models)
        else:
            configs = (
                provider_configs
                if provider_configs is not None
                else build_provider_configs(settings)
            )
            self._models = {name: create_chat_model(cfg) for name, cfg in configs.items()}

        if not self._models:
            logger.warning("LLM 网关未配置任何可用 provider，调用时将抛出 LLMGatewayError")

        # 默认模型：显式指定 > 配置默认（若已注册）> 任一可用
        if default_model is not None:
            self._current_model = default_model
        elif settings.llm_default_model in self._models:
            self._current_model = settings.llm_default_model
        elif self._models:
            self._current_model = next(iter(self._models))
        else:
            self._current_model = ""

        # fallback 顺序：显式指定 > 配置解析，并补齐未列入但已注册的模型
        if fallback_order is not None:
            self._fallback_order = list(fallback_order)
        else:
            order = [m.strip() for m in settings.llm_fallback_order.split(",") if m.strip()]
            self._fallback_order = [m for m in order if m in self._models]
            for m in self._models:
                if m not in self._fallback_order:
                    self._fallback_order.append(m)

    @property
    def current_model(self) -> str:
        return self._current_model

    def list_models(self) -> list[str]:
        return list(self._models.keys())

    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """返回指定模型（或当前默认）的原始 BaseChatModel。

        返回原始对象以便 LangGraph Agent（T16）自行调用 .bind_tools() /
        .with_structured_output()，fallback 逻辑只封装在网关方法内。
        """
        name = model_name or self._current_model
        if name not in self._models:
            raise UnknownModelError(
                f"Unknown model '{name}'. Available: {self.list_models()}"
            )
        return self._models[name]

    def set_default_model(self, model_name: str) -> None:
        """运行时热切换默认模型。名称无效则抛异常且不改变现状。"""
        if model_name not in self._models:
            raise UnknownModelError(
                f"Unknown model '{model_name}'. Available: {self.list_models()}"
            )
        old = self._current_model
        self._current_model = model_name
        logger.info("LLM 默认模型切换: {} -> {}", old, model_name)

    def _resolve_chain(self, model: str | None) -> list[str]:
        """构建本次调用的供应商尝试顺序：主模型 + 其余 fallback。"""
        primary = model or self._current_model
        if primary not in self._models:
            raise UnknownModelError(
                f"Unknown model '{primary}'. Available: {self.list_models()}"
            )
        return [primary] + [m for m in self._fallback_order if m != primary]

    async def ainvoke(
        self,
        messages: str | list[BaseMessage],
        model: str | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        """非流式调用，主模型失败则依次尝试 fallback，全部失败抛 AllProvidersFailedError。"""
        if not self._models:
            raise LLMGatewayError("No LLM providers configured")

        chain = self._resolve_chain(model)
        errors: dict[str, Exception] = {}
        for name in chain:
            llm = self._models[name]
            try:
                return await llm.ainvoke(messages, **kwargs)
            except Exception as exc:  # noqa: BLE001 - 需捕获所有供应商异常以触发 fallback
                logger.warning("LLM provider 调用失败 | model={} | error={}", name, exc)
                errors[name] = exc
        raise AllProvidersFailedError(errors)

    async def astream(
        self,
        messages: str | list[BaseMessage],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        """流式调用。

        fallback 仅在**首个 chunk 产出前**生效：若某供应商在输出任何内容前失败，
        切换到下一个供应商；一旦已开始输出，中途失败将直接抛出——静默切换会导致
        SSE（T18）出现重复或错乱文本。
        """
        if not self._models:
            raise LLMGatewayError("No LLM providers configured")

        chain = self._resolve_chain(model)
        errors: dict[str, Exception] = {}
        for name in chain:
            llm = self._models[name]
            yielded_any = False
            try:
                async for chunk in llm.astream(messages, **kwargs):
                    yielded_any = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                if yielded_any:
                    logger.error("LLM provider 流式中断(已输出部分内容) | model={} | error={}", name, exc)
                    raise
                logger.warning("LLM provider 流式失败(首chunk前) | model={} | error={}", name, exc)
                errors[name] = exc
        raise AllProvidersFailedError(errors)

    # 兼容规划文档 §3.2.4 的命名
    chat_with_fallback = astream


@lru_cache
def get_llm_gateway() -> LLMGateway:
    """网关单例访问器（对齐 get_settings 模式）。"""
    return LLMGateway()


__all__ = [
    "AIMessage",
    "AllProvidersFailedError",
    "LLMGateway",
    "LLMGatewayError",
    "UnknownModelError",
    "get_llm_gateway",
]
