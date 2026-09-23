"""LLM 网关：多模型热切换 + Adapter 隔离 + fallback。

上层（简历解析、画像构建、Agent、SSE 对话）统一通过 get_llm_gateway() 调用，
不直接接触 langchain SDK。LangSmith 追踪由环境变量全局启用，无需在此处理。

模型表来源（B2-1 起）：
    显式注入(provider_configs/models，测试用) > DB 快照(app.core.llm.registry) > env 配置。
DB 无任何配置时快照为空 → 行为与接入前完全一致（纯 env）。

功能路由（B2-1）：调用方传 `function_key=`（如 "job_quality"），网关照 DB 绑定选模型；
未绑定/绑定不可用则回落当前默认模型 —— 于是管理端「保存即生效」无需重启。
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
from app.core.llm.registry import get_registry_snapshot


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

        # 显式注入时完全不读 DB 快照：测试（与未来多租户场景）不受库里配置影响
        snapshot = (
            None if (models is not None or provider_configs is not None) else get_registry_snapshot()
        )

        # 模型注册表：注入的 models > 注入的 provider_configs > DB 快照 > env
        if models is not None:
            self._models: dict[str, BaseChatModel] = dict(models)
            self.config_source = "injected"
        else:
            from_registry = False
            if provider_configs is None and snapshot is not None and snapshot.chat_configs:
                provider_configs = snapshot.chat_configs
                from_registry = True
            configs = (
                provider_configs
                if provider_configs is not None
                else build_provider_configs(settings)
            )
            self._models = {name: create_chat_model(cfg) for name, cfg in configs.items()}
            self.config_source = "db" if from_registry else "env"

        if not self._models:
            logger.warning("LLM 网关未配置任何可用 provider，调用时将抛出 LLMGatewayError")

        # 功能键 → 网关模型 key（仅 chat；embedding 走 embeddings 客户端）
        self._function_routes: dict[str, str] = {}
        if snapshot is not None:
            self._function_routes = {
                key: spec.gateway_key
                for key, spec in snapshot.routes.items()
                if spec.kind == "chat" and spec.gateway_key in self._models
            }

        # 默认模型：显式指定 > DB 的 default 路由 > 配置默认（若已注册）> 任一可用
        if default_model is not None:
            self._current_model = default_model
        elif snapshot is not None and snapshot.default_gateway_key in self._models:
            self._current_model = snapshot.default_gateway_key
        elif settings.llm_default_model in self._models:
            self._current_model = settings.llm_default_model
        elif self._models:
            self._current_model = next(iter(self._models))
        else:
            self._current_model = ""

        # fallback 顺序：显式指定 > env 顺序（命中 DB 模型名时）> DB 顺序，并补齐未列入的模型
        order: list[str] = []
        if fallback_order is not None:
            order = list(fallback_order)
        else:
            env_order = [m.strip() for m in settings.llm_fallback_order.split(",") if m.strip()]
            registry_order = list(snapshot.fallback_order) if snapshot is not None else []
            for candidate in (env_order, registry_order):
                for name in candidate:
                    if name in self._models and name not in order:
                        order.append(name)
        for name in self._models:
            if name not in order:
                order.append(name)
        self._fallback_order = order

    @property
    def current_model(self) -> str:
        return self._current_model

    def list_models(self) -> list[str]:
        return list(self._models.keys())

    def list_function_routes(self) -> dict[str, str]:
        """当前生效的功能键绑定（未配置的不出现）。"""
        return dict(self._function_routes)

    def resolve_function_key(self, function_key: str | None) -> str | None:
        """把功能键解析成已注册的模型 key；未配置或不可用返回 None（调用方回落默认）。"""
        if not function_key:
            return None
        name = self._function_routes.get(function_key)
        if name is None or name not in self._models:
            logger.debug("功能键 {} 未绑定可用模型，回落默认 {}", function_key, self._current_model)
            return None
        return name

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

    def _resolve_chain(self, model: str | None, function_key: str | None = None) -> list[str]:
        """构建本次调用的供应商尝试顺序：主模型 + 其余 fallback。

        主模型选择：显式 model > 功能键绑定 > 当前默认。
        """
        primary = model or self.resolve_function_key(function_key) or self._current_model
        if primary not in self._models:
            raise UnknownModelError(
                f"Unknown model '{primary}'. Available: {self.list_models()}"
            )
        return [primary] + [m for m in self._fallback_order if m != primary]

    async def ainvoke(
        self,
        messages: str | list[BaseMessage],
        model: str | None = None,
        function_key: str | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        """非流式调用，主模型失败则依次尝试 fallback，全部失败抛 AllProvidersFailedError。"""
        if not self._models:
            raise LLMGatewayError("No LLM providers configured")

        chain = self._resolve_chain(model, function_key)
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
        function_key: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        """流式调用。

        fallback 仅在**首个 chunk 产出前**生效：若某供应商在输出任何内容前失败，
        切换到下一个供应商；一旦已开始输出，中途失败将直接抛出——静默切换会导致
        SSE（T18）出现重复或错乱文本。
        """
        if not self._models:
            raise LLMGatewayError("No LLM providers configured")

        chain = self._resolve_chain(model, function_key)
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


def clear_gateway_cache() -> None:
    """清掉网关单例 —— 管理端保存模型配置后由 registry.invalidate_llm_registry() 调用。"""
    get_llm_gateway.cache_clear()


__all__ = [
    "AIMessage",
    "AllProvidersFailedError",
    "LLMGateway",
    "LLMGatewayError",
    "UnknownModelError",
    "clear_gateway_cache",
    "get_llm_gateway",
]
