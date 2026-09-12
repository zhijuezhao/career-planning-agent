"""LLM 网关离线单元测试（零网络调用，全部使用注入的 fake 模型）。"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
from app.core.llm.gateway import (
    AllProvidersFailedError,
    LLMGateway,
    LLMGatewayError,
    UnknownModelError,
    get_llm_gateway,
)
from app.core.llm.models import (
    LLMProviderConfig,
    build_provider_configs,
    create_chat_model,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import SecretStr


class FailingChatModel(BaseChatModel):
    """所有调用都立即失败的假模型。"""

    error_message: str = "provider down"

    @property
    def _llm_type(self) -> str:
        return "failing"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        raise RuntimeError(self.error_message)

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        raise RuntimeError(self.error_message)

    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        raise RuntimeError(self.error_message)
        yield  # pragma: no cover - 使本函数成为 async generator


class StreamThenFailModel(BaseChatModel):
    """先产出若干 chunk，再在中途失败。"""

    chunks_before_fail: int = 2

    @property
    def _llm_type(self) -> str:
        return "stream-then-fail"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        for i in range(self.chunks_before_fail):
            yield ChatGenerationChunk(message=AIMessageChunk(content=f"c{i}"))
        raise RuntimeError("mid-stream failure")


def make_gateway(models: dict[str, BaseChatModel], default: str, order: list[str]) -> LLMGateway:
    return LLMGateway(models=models, default_model=default, fallback_order=order)


# ---------- get_model / 注册表 ----------

def test_get_model_returns_default():
    d = FakeListChatModel(responses=["x"])
    gw = make_gateway({"deepseek": d}, "deepseek", ["deepseek"])
    assert gw.get_model() is d
    assert gw.get_model("deepseek") is d
    assert gw.current_model == "deepseek"
    assert gw.list_models() == ["deepseek"]


def test_get_model_unknown_raises():
    gw = make_gateway({"deepseek": FakeListChatModel(responses=["x"])}, "deepseek", ["deepseek"])
    with pytest.raises(UnknownModelError):
        gw.get_model("nonexistent")


def test_set_default_model_hot_switch():
    d = FakeListChatModel(responses=["d"])
    q = FakeListChatModel(responses=["q"])
    gw = make_gateway({"deepseek": d, "qwen": q}, "deepseek", ["deepseek", "qwen"])
    gw.set_default_model("qwen")
    assert gw.current_model == "qwen"
    assert gw.get_model() is q


def test_set_default_model_unknown_keeps_old():
    d = FakeListChatModel(responses=["d"])
    gw = make_gateway({"deepseek": d}, "deepseek", ["deepseek"])
    with pytest.raises(UnknownModelError):
        gw.set_default_model("nope")
    assert gw.current_model == "deepseek"


# ---------- ainvoke ----------

async def test_ainvoke_success():
    d = FakeListChatModel(responses=["from-deepseek"])
    gw = make_gateway({"deepseek": d}, "deepseek", ["deepseek"])
    result = await gw.ainvoke("hi")
    assert result.content == "from-deepseek"


async def test_ainvoke_fallback_on_primary_failure():
    failing = FailingChatModel()
    ok = FakeListChatModel(responses=["qwen-ok"])
    gw = make_gateway({"deepseek": failing, "qwen": ok}, "deepseek", ["deepseek", "qwen"])
    result = await gw.ainvoke("hi")
    assert result.content == "qwen-ok"


async def test_ainvoke_all_fail_raises():
    gw = make_gateway(
        {"deepseek": FailingChatModel(), "qwen": FailingChatModel()},
        "deepseek",
        ["deepseek", "qwen"],
    )
    with pytest.raises(AllProvidersFailedError) as ei:
        await gw.ainvoke("hi")
    assert set(ei.value.errors.keys()) == {"deepseek", "qwen"}


async def test_explicit_model_kwarg_overrides_default():
    d = FakeListChatModel(responses=["from-deepseek"])
    q = FakeListChatModel(responses=["from-qwen"])
    gw = make_gateway({"deepseek": d, "qwen": q}, "deepseek", ["deepseek", "qwen"])
    result = await gw.ainvoke("hi", model="qwen")
    assert result.content == "from-qwen"


async def test_empty_gateway_raises_llm_gateway_error():
    gw = LLMGateway(models={}, default_model="", fallback_order=[])
    with pytest.raises(LLMGatewayError):
        await gw.ainvoke("hi")


# ---------- astream ----------

async def test_astream_success_yields_chunks():
    ok = FakeListChatModel(responses=["hello"])
    gw = make_gateway({"deepseek": ok}, "deepseek", ["deepseek"])
    chunks = [c async for c in gw.astream("hi")]
    assert len(chunks) >= 1
    assert "".join(c.content for c in chunks) == "hello"


async def test_astream_fallback_before_first_chunk():
    failing = FailingChatModel()
    ok = FakeListChatModel(responses=["qwen-stream"])
    gw = make_gateway({"deepseek": failing, "qwen": ok}, "deepseek", ["deepseek", "qwen"])
    chunks = [c async for c in gw.astream("hi")]
    assert "".join(c.content for c in chunks) == "qwen-stream"


async def test_astream_midstream_failure_propagates():
    gw = make_gateway(
        {"deepseek": StreamThenFailModel(chunks_before_fail=2)},
        "deepseek",
        ["deepseek", "qwen"],
    )
    collected: list[AIMessageChunk] = []
    with pytest.raises(RuntimeError):
        async for c in gw.astream("hi"):
            collected.append(c)
    assert len(collected) == 2  # 已输出的 chunk 不被静默丢弃或切换


# ---------- models.py ----------

def test_build_provider_configs_skips_empty_keys(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep")
    monkeypatch.setenv("QWEN_API_KEY", "")
    get_settings.cache_clear()
    try:
        configs = build_provider_configs()
        assert "deepseek" in configs
        assert "qwen" not in configs
    finally:
        get_settings.cache_clear()


def test_build_provider_configs_maps_settings_fields(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")
    get_settings.cache_clear()
    try:
        cfg = build_provider_configs()["deepseek"]
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 2048
        assert cfg.base_url == "https://api.deepseek.com/v1"
        assert cfg.model_name == "deepseek-chat"
        assert cfg.api_key.get_secret_value() == "sk-x"
    finally:
        get_settings.cache_clear()


def test_create_chat_model_returns_base_chat_model():
    cfg = LLMProviderConfig(
        name="t",
        api_key=SecretStr("sk-x"),
        base_url="https://example.com/v1",
        model_name="m",
    )
    model = create_chat_model(cfg)
    assert isinstance(model, BaseChatModel)


def test_get_llm_gateway_is_singleton():
    get_llm_gateway.cache_clear()
    try:
        assert get_llm_gateway() is get_llm_gateway()
    finally:
        get_llm_gateway.cache_clear()
