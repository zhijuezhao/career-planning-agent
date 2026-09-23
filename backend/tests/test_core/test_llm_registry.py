"""B2-1 单元测试：密钥加密/掩码、registry 快照构建、网关功能键路由。

不连数据库：`load_snapshot` 用假 session（只实现它用到的 `execute(select(Entity))`），
网关用「手工快照 + 假 base_url」构造真实 ChatOpenAI 实例（构造不发网络请求）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.core.llm.gateway import LLMGateway, clear_gateway_cache
from app.core.llm.registry import (
    RegistrySnapshot,
    RouteSpec,
    clear_registry_snapshot,
    load_snapshot,
    set_registry_snapshot,
)
from app.core.llm.secrets import decrypt_secret, encrypt_secret, is_encrypted, mask_secret
from app.domain.models.llm_config import LLMModel, LLMProvider, LLMRoute
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── 假 DB ───────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """只实现 load_snapshot 用到的 `execute(select(Entity)).scalars().all()`。"""

    def __init__(self, providers=(), models=(), routes=()):
        self._map = {
            LLMProvider: list(providers),
            LLMModel: list(models),
            LLMRoute: list(routes),
        }

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return _FakeResult(self._map[entity])


def _provider(pid=1, name="prov", enabled=True, api_key="sk-abcdefgh1234", sort_order=0):
    return LLMProvider(
        id=pid,
        name=name,
        base_url="http://127.0.0.1:9/v1",
        api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        enabled=enabled,
        sort_order=sort_order,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _model(mid=1, provider_id=1, name="chat-model", kind="chat", enabled=True, dim=None):
    return LLMModel(
        id=mid,
        provider_id=provider_id,
        model_name=name,
        display_name=None,
        kind=kind,
        dim=dim,
        temperature=None,
        max_tokens=None,
        enabled=enabled,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _route(rid=1, function_key="job_extract", model_id=1):
    return LLMRoute(
        id=rid, function_key=function_key, model_id=model_id, created_at=_NOW, updated_at=_NOW
    )


# ── 密钥 ────────────────────────────────────────────────────────────────────


class TestSecrets:
    def test_encrypt_decrypt_roundtrip(self):
        cipher = encrypt_secret("sk-abcdefgh1234")
        assert is_encrypted(cipher)
        assert cipher.startswith("enc:v1:")
        assert cipher != "sk-abcdefgh1234"
        assert decrypt_secret(cipher) == "sk-abcdefgh1234"

    def test_empty_value(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret(None) == ""
        assert decrypt_secret("") == ""

    def test_legacy_plaintext_passthrough(self):
        """历史明文（ai_configs 现状）必须仍可读，否则要数据迁移。"""
        assert decrypt_secret("sk-plain-legacy") == "sk-plain-legacy"
        assert not is_encrypted("sk-plain-legacy")

    def test_double_encrypt_guard(self):
        cipher = encrypt_secret("sk-abcdefgh1234")
        assert encrypt_secret(cipher) == cipher

    def test_broken_ciphertext_returns_empty(self):
        assert decrypt_secret("enc:v1:not-a-real-token") == ""

    def test_mask_never_leaks_middle(self):
        assert mask_secret("sk-abcdefgh1234") == "sk-***1234"
        assert mask_secret("short12") == "***rt12"  # 短密钥只保留末 4 位
        assert mask_secret(None) == ""


# ── registry 快照 ───────────────────────────────────────────────────────────


class TestLoadSnapshot:
    async def test_empty_db_is_env_mode(self):
        snap = await load_snapshot(_FakeSession())
        assert snap.source == "env"
        assert snap.chat_configs == {}
        assert snap.routes == {}
        assert snap.fallback_order == ()
        assert snap.default_gateway_key is None
        assert snap.embedding is None

    async def test_chat_models_and_embedding_split(self):
        session = _FakeSession(
            providers=[_provider()],
            models=[
                _model(1, name="chat-model", kind="chat"),
                _model(2, name="embed-model", kind="embedding", dim=1024),
            ],
        )
        snap = await load_snapshot(session)
        assert snap.source == "db"
        assert list(snap.chat_configs) == ["prov:chat-model"]
        assert snap.chat_labels["prov:chat-model"] == "chat-model"
        assert snap.chat_configs["prov:chat-model"].model_name == "chat-model"

    async def test_disabled_provider_or_model_skipped(self):
        session = _FakeSession(
            providers=[_provider(1, "on"), _provider(2, "off", enabled=False)],
            models=[
                _model(1, provider_id=1, name="ok"),
                _model(2, provider_id=1, name="disabled-model", enabled=False),
                _model(3, provider_id=2, name="provider-off"),
            ],
        )
        snap = await load_snapshot(session)
        assert list(snap.chat_configs) == ["on:ok"]
        assert snap.fallback_order == ("on:ok",)

    async def test_provider_without_api_key_skipped(self):
        session = _FakeSession(providers=[_provider(api_key="")], models=[_model()])
        snap = await load_snapshot(session)
        assert snap.chat_configs == {}
        assert snap.source == "env"

    async def test_route_bound_when_kind_matches(self):
        session = _FakeSession(
            providers=[_provider()],
            models=[_model(1, name="chat-model")],
            routes=[_route(1, "job_extract", 1)],
        )
        snap = await load_snapshot(session)
        assert list(snap.routes) == ["job_extract"]
        spec = snap.routes["job_extract"]
        assert spec.gateway_key == "prov:chat-model"
        assert spec.api_key == "sk-abcdefgh1234"

    async def test_route_ignored_on_kind_mismatch(self):
        """chat 功能键绑到 embedding 模型 → 视为未配置（回退），不能静默生效。"""
        session = _FakeSession(
            providers=[_provider()],
            models=[_model(1, name="embed-model", kind="embedding")],
            routes=[_route(1, "job_extract", 1)],
        )
        snap = await load_snapshot(session)
        assert snap.routes == {}

    async def test_route_ignored_when_model_disabled_or_missing(self):
        session = _FakeSession(
            providers=[_provider()],
            models=[_model(1, name="chat-model", enabled=False)],
            routes=[_route(1, "job_extract", 1), _route(2, "job_portrait", 999)],
        )
        snap = await load_snapshot(session)
        assert snap.routes == {}

    async def test_default_and_embedding_properties(self):
        session = _FakeSession(
            providers=[_provider()],
            models=[_model(1, name="chat-model"), _model(2, name="embed-model", kind="embedding")],
            routes=[_route(1, "default", 1), _route(2, "embedding", 2)],
        )
        snap = await load_snapshot(session)
        assert snap.default_gateway_key == "prov:chat-model"
        assert snap.embedding is not None
        assert snap.embedding.model_name == "embed-model"
        assert snap.embedding.gateway_key == "prov:embed-model"

    async def test_fallback_order_follows_provider_sort_order(self):
        session = _FakeSession(
            providers=[_provider(1, "b", sort_order=2), _provider(2, "a", sort_order=1)],
            models=[_model(1, provider_id=1, name="m1"), _model(2, provider_id=2, name="m2")],
        )
        snap = await load_snapshot(session)
        assert snap.fallback_order == ("a:m2", "b:m1")


# ── 网关功能键路由 ──────────────────────────────────────────────────────────


def _route_spec(function_key="job_quality", kind="chat", model_name="chat-model"):
    return RouteSpec(
        function_key=function_key,
        provider_id=1,
        provider_name="prov",
        model_id=1,
        model_name=model_name,
        kind=kind,
        base_url="http://127.0.0.1:9/v1",
        api_key="sk-abcdefgh1234",
        temperature=0.1,
        max_tokens=64,
        dim=None,
    )


def _chat_config():
    from app.core.llm.models import LLMProviderConfig
    from pydantic import SecretStr

    return LLMProviderConfig(
        name="prov:chat-model",
        api_key=SecretStr("sk-abcdefgh1234"),
        base_url="http://127.0.0.1:9/v1",
        model_name="chat-model",
        temperature=0.1,
        max_tokens=64,
    )


@pytest.fixture
def db_snapshot():
    """装一份「DB 已配置」的快照，用例结束后彻底恢复（避免污染其他测试）。"""
    snapshot = RegistrySnapshot(
        version=42,
        loaded_at=_NOW,
        routes={"job_quality": _route_spec()},
        chat_configs={"prov:chat-model": _chat_config()},
        fallback_order=("prov:chat-model",),
        chat_labels={"prov:chat-model": "chat-model"},
    )
    set_registry_snapshot(snapshot)
    clear_gateway_cache()
    try:
        yield snapshot
    finally:
        clear_registry_snapshot()
        clear_gateway_cache()


class TestGatewayFunctionRouting:
    def test_gateway_built_from_db_snapshot(self, db_snapshot):
        gateway = LLMGateway()
        assert gateway.config_source == "db"
        assert gateway.list_models() == ["prov:chat-model"]
        assert gateway.current_model == "prov:chat-model"

    def test_function_key_resolves_to_bound_model(self, db_snapshot):
        gateway = LLMGateway()
        assert gateway.list_function_routes() == {"job_quality": "prov:chat-model"}
        assert gateway.resolve_function_key("job_quality") == "prov:chat-model"
        # 未绑定的功能键 → None → 调用方回落默认模型
        assert gateway.resolve_function_key("job_portrait") is None
        assert gateway.resolve_function_key(None) is None

    def test_resolve_chain_prefers_function_key(self, db_snapshot):
        gateway = LLMGateway()
        assert gateway._resolve_chain(None, "job_quality")[0] == "prov:chat-model"
        assert gateway._resolve_chain(None, "job_portrait")[0] == "prov:chat-model"

    def test_default_route_becomes_current_model(self):
        snapshot = RegistrySnapshot(
            version=1,
            loaded_at=_NOW,
            routes={"default": _route_spec("default")},
            chat_configs={"prov:chat-model": _chat_config()},
            fallback_order=("prov:chat-model",),
            chat_labels={},
        )
        set_registry_snapshot(snapshot)
        clear_gateway_cache()
        try:
            gateway = LLMGateway()
            assert gateway.current_model == "prov:chat-model"
        finally:
            clear_registry_snapshot()
            clear_gateway_cache()

    def test_injected_models_ignore_db_snapshot(self, db_snapshot):
        fake = FakeListChatModel(responses=["x"])
        gateway = LLMGateway(models={"fake": fake})
        assert gateway.config_source == "injected"
        assert gateway.resolve_function_key("job_quality") is None

    def test_without_snapshot_falls_back_to_env(self):
        clear_registry_snapshot()
        clear_gateway_cache()
        gateway = LLMGateway()
        assert gateway.config_source in {"env", "injected"}
        assert gateway.list_function_routes() == {}


class TestRouteSpec:
    def test_gateway_key_and_label(self):
        spec = _route_spec()
        assert spec.gateway_key == "prov:chat-model"
        assert spec.label == "prov:chat-model"
