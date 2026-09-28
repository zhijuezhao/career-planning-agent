"""B2-1 管理端「模型配置中心」API 测试（真实 dev DB，验证热生效与掩码）。

约定：
    * 本模块只创建/删除自己的 `b21_<ts>_*` 供应商（级联带走模型与路由），
      不碰库里其他人的配置；结束时重建 registry 快照，避免影响其他测试模块。
    * 假供应商 base_url 指到 `http://127.0.0.1:9/v1`（必然拒连），
      于是「连通性测试」用例不会真的打外网，且失败原因可预期。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.core.llm.embeddings import clear_embeddings_cache, get_embeddings
from app.core.llm.gateway import clear_gateway_cache, get_llm_gateway
from app.core.llm.registry import (
    clear_registry_snapshot,
    get_registry_snapshot,
    invalidate_llm_registry,
    reload_registry,
)
from app.core.llm.secrets import decrypt_secret
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from tests.conftest import test_session_factory

_ts = str(int(time.time()))
_PREFIX = f"b21_{_ts}"
_BOGUS_BASE_URL = "http://127.0.0.1:9/v1"
_API_KEY = "sk-abcdefgh1234"

pytestmark = pytest.mark.usefixtures("clean_llm_registry")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _cleanup_rows() -> None:
    """删除本模块创建的供应商（级联模型/路由）并重建快照。"""

    async def _run() -> None:
        from app.domain.models.llm_config import LLMModel, LLMProvider

        async with test_session_factory() as session:
            provider_ids = list(
                (
                    await session.execute(
                        select(LLMProvider.id).where(LLMProvider.name.like(f"{_PREFIX}%"))
                    )
                )
                .scalars()
                .all()
            )
            if provider_ids:
                # 显式解开仍指向这些模型的绑定，再删供应商（不依赖级联顺序）
                model_ids = list(
                    (
                        await session.execute(
                            select(LLMModel.id).where(LLMModel.provider_id.in_(provider_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                if model_ids:
                    await session.execute(
                        text("DELETE FROM llm_routes WHERE model_id = ANY(:ids)"),
                        {"ids": model_ids},
                    )
                await session.execute(
                    text("DELETE FROM llm_providers WHERE id = ANY(:ids)"), {"ids": provider_ids}
                )
            await session.commit()
            await reload_registry(session)
            await session.commit()
        invalidate_llm_registry()

    asyncio.run(_run())


@pytest.fixture(scope="module")
def clean_llm_registry():
    """进模块前先清一次（防上次中断残留），出模块后彻底恢复。"""
    _cleanup_rows()
    yield
    _cleanup_rows()
    clear_registry_snapshot()
    clear_gateway_cache()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def provider(client: TestClient, admin_token: str) -> dict:
    resp = client.post(
        "/api/v1/admin/system/providers",
        json={
            "name": f"{_PREFIX}_p1",
            "base_url": _BOGUS_BASE_URL,
            "api_key": _API_KEY,
            "sort_order": 7,
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def chat_model(client: TestClient, admin_token: str, provider: dict) -> dict:
    resp = client.post(
        "/api/v1/admin/system/models",
        json={
            "provider_id": provider["id"],
            "model_name": "chat-model-x",
            "display_name": "测试对话模型",
            "kind": "chat",
            "temperature": 0.2,
            "max_tokens": 512,
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def embed_model(client: TestClient, admin_token: str, provider: dict) -> dict:
    resp = client.post(
        "/api/v1/admin/system/models",
        json={
            "provider_id": provider["id"],
            "model_name": "embed-model-x",
            "kind": "embedding",
            "dim": 1024,
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def embed_model_2(client: TestClient, admin_token: str, provider: dict) -> dict:
    resp = client.post(
        "/api/v1/admin/system/models",
        json={
            "provider_id": provider["id"],
            "model_name": "embed-model-y",
            "kind": "embedding",
            "dim": 1024,
        },
        headers=_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _routes(client: TestClient, token: str) -> dict[str, dict]:
    resp = client.get("/api/v1/admin/system/routes", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    return {item["function_key"]: item for item in resp.json()["items"]}


def _bind(client: TestClient, token: str, function_key: str, model_id: int | None):
    return client.put(
        f"/api/v1/admin/system/routes/{function_key}",
        json={"model_id": model_id},
        headers=_headers(token),
    )


# ── 鉴权 ────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_providers_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = client.get("/api/v1/admin/system/providers", headers=_headers(student_token))
        assert resp.status_code == 403

    def test_bind_route_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = _bind(client, student_token, "job_extract", 1)
        assert resp.status_code == 403


# ── 供应商 ──────────────────────────────────────────────────────────────────


class TestProviders:
    def test_created_provider_masks_api_key(self, provider: dict):
        assert provider["name"] == f"{_PREFIX}_p1"
        assert provider["api_key_set"] is True
        assert provider["api_key_masked"] == "sk-***1234"
        assert "api_key" not in provider  # 只回掩码，不回明文/密文
        assert provider["model_count"] == 0

    def test_list_providers_with_model_count(self, client, admin_token, provider, chat_model):
        resp = client.get("/api/v1/admin/system/providers", headers=_headers(admin_token))
        assert resp.status_code == 200
        items = {item["id"]: item for item in resp.json()["items"]}
        assert items[provider["id"]]["model_count"] >= 1

    def test_duplicate_name_conflict(self, client, admin_token, provider):
        resp = client.post(
            "/api/v1/admin/system/providers",
            json={"name": provider["name"], "base_url": _BOGUS_BASE_URL, "api_key": "sk-x"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 409

    def test_api_key_stored_encrypted(self, provider):
        """库里必须是密文（enc:v1:），而明文仍能解出来给网关用。"""

        async def _fetch() -> str | None:
            from app.domain.models.llm_config import LLMProvider

            async with test_session_factory() as session:
                return (
                    await session.execute(
                        select(LLMProvider.api_key_encrypted).where(LLMProvider.id == provider["id"])
                    )
                ).scalar_one()

        stored = asyncio.run(_fetch())
        assert stored is not None and stored.startswith("enc:v1:")
        assert _API_KEY not in stored
        assert decrypt_secret(stored) == _API_KEY

    def test_disable_and_reenable_provider(self, client, admin_token, provider):
        off = client.put(
            f"/api/v1/admin/system/providers/{provider['id']}",
            json={"enabled": False},
            headers=_headers(admin_token),
        )
        assert off.status_code == 200 and off.json()["enabled"] is False
        # 禁用后该供应商的模型退出网关（回退 env）
        gateway = get_llm_gateway()
        assert f"{provider['name']}:chat-model-x" not in gateway.list_models()

        on = client.put(
            f"/api/v1/admin/system/providers/{provider['id']}",
            json={"enabled": True},
            headers=_headers(admin_token),
        )
        assert on.status_code == 200 and on.json()["enabled"] is True

    def test_delete_unknown_provider_404(self, client, admin_token):
        resp = client.delete(
            "/api/v1/admin/system/providers/99999999", headers=_headers(admin_token)
        )
        assert resp.status_code == 404

    def test_delete_provider_cascades(self, client, admin_token):
        created = client.post(
            "/api/v1/admin/system/providers",
            json={"name": f"{_PREFIX}_temp", "base_url": _BOGUS_BASE_URL, "api_key": _API_KEY},
            headers=_headers(admin_token),
        ).json()
        model = client.post(
            "/api/v1/admin/system/models",
            json={"provider_id": created["id"], "model_name": "temp-model", "kind": "chat"},
            headers=_headers(admin_token),
        ).json()
        assert _bind(client, admin_token, "job_extract", model["id"]).status_code == 200

        resp = client.delete(
            f"/api/v1/admin/system/providers/{created['id']}", headers=_headers(admin_token)
        )
        assert resp.status_code == 204
        # 模型与路由都被级联清掉 → 功能键回到 env
        assert _routes(client, admin_token)["job_extract"]["source"] == "env"
        assert get_llm_gateway().resolve_function_key("job_extract") is None


# ── 模型 ────────────────────────────────────────────────────────────────────


class TestModels:
    def test_create_model_unknown_provider_404(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/system/models",
            json={"provider_id": 99999999, "model_name": "x", "kind": "chat"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 404

    def test_duplicate_model_conflict(self, client, admin_token, provider, chat_model):
        resp = client.post(
            "/api/v1/admin/system/models",
            json={
                "provider_id": provider["id"],
                "model_name": chat_model["model_name"],
                "kind": "chat",
            },
            headers=_headers(admin_token),
        )
        assert resp.status_code == 409

    def test_filter_by_kind(self, client, admin_token, embed_model):
        resp = client.get(
            "/api/v1/admin/system/models", params={"kind": "embedding"}, headers=_headers(admin_token)
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items and all(item["kind"] == "embedding" for item in items)
        assert any(item["id"] == embed_model["id"] for item in items)

    def test_update_model_fields(self, client, admin_token, chat_model):
        resp = client.put(
            f"/api/v1/admin/system/models/{chat_model['id']}",
            json={"temperature": 0.9, "max_tokens": 2048, "display_name": "改过的名字"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["temperature"] == 0.9
        assert data["max_tokens"] == 2048
        assert data["display_name"] == "改过的名字"

    def test_invalid_kind_rejected(self, client, admin_token, provider):
        resp = client.post(
            "/api/v1/admin/system/models",
            json={"provider_id": provider["id"], "model_name": "bad", "kind": "rerank"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 422


# ── 功能路由（含热生效）──────────────────────────────────────────────────────


class TestRoutes:
    def test_routes_cover_all_function_keys_including_b3_b4(self, client, admin_token):
        routes = _routes(client, admin_token)
        assert {
            "default",
            "job_quality",
            "job_extract",
            "job_portrait",
            "job_link_extract",
            "resume_parse",
            "embedding",
        } <= set(routes)
        assert routes["embedding"]["kind"] == "embedding"

    def test_bind_chat_route_hot_switch(self, client, admin_token, provider, chat_model):
        key = f"{provider['name']}:{chat_model['model_name']}"
        assert _routes(client, admin_token)["job_extract"]["source"] == "env"
        assert get_llm_gateway().resolve_function_key("job_extract") is None

        try:
            resp = _bind(client, admin_token, "job_extract", chat_model["id"])
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["source"] == "db"
            assert data["effective"] == key
            assert data["warning"] is None

            # 关键验收：同一进程内无需重启即生效
            gateway = get_llm_gateway()
            assert gateway.config_source == "db"
            assert gateway.resolve_function_key("job_extract") == key
            assert key in gateway.list_models()
            assert get_registry_snapshot().routes["job_extract"].model_id == chat_model["id"]
        finally:
            assert _bind(client, admin_token, "job_extract", None).status_code == 200

        assert _routes(client, admin_token)["job_extract"]["source"] == "env"
        assert get_llm_gateway().resolve_function_key("job_extract") is None

    def test_bind_kind_mismatch_409(self, client, admin_token, embed_model):
        resp = _bind(client, admin_token, "job_extract", embed_model["id"])
        assert resp.status_code == 409

    def test_rebind_embedding_route_clears_embeddings_cache(
        self, client, admin_token, embed_model, embed_model_2
    ):
        """换向量模型必须清缓存，否则仍用旧模型（B2-1 明确要求）。"""
        try:
            assert _bind(client, admin_token, "embedding", embed_model["id"]).status_code == 200
            get_embeddings()  # 用 DB 配置填充 lru_cache（假地址只构造、不发请求）
            assert get_embeddings.cache_info().currsize == 1
            snapshot = get_registry_snapshot()
            assert snapshot is not None and snapshot.embedding is not None
            assert snapshot.embedding.model_name == "embed-model-x"

            assert _bind(client, admin_token, "embedding", embed_model_2["id"]).status_code == 200
            assert get_embeddings.cache_info().currsize == 0
            snapshot = get_registry_snapshot()
            assert snapshot is not None and snapshot.embedding is not None
            assert snapshot.embedding.model_name == "embed-model-y"
        finally:
            assert _bind(client, admin_token, "embedding", None).status_code == 200

        snapshot = get_registry_snapshot()
        assert snapshot is not None and snapshot.embedding is None

    def test_unknown_function_key_404(self, client, admin_token, chat_model):
        resp = _bind(client, admin_token, "not_a_function", chat_model["id"])
        assert resp.status_code == 404

    def test_unknown_model_404(self, client, admin_token):
        resp = _bind(client, admin_token, "job_extract", 99999999)
        assert resp.status_code == 404

    def test_missing_model_id_422(self, client, admin_token):
        resp = client.put(
            "/api/v1/admin/system/routes/job_extract",
            json={},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 422

    def test_disabled_model_not_effective(self, client, admin_token, provider, chat_model):
        try:
            assert _bind(client, admin_token, "job_portrait", chat_model["id"]).status_code == 200
            assert _routes(client, admin_token)["job_portrait"]["source"] == "db"

            off = client.put(
                f"/api/v1/admin/system/models/{chat_model['id']}",
                json={"enabled": False},
                headers=_headers(admin_token),
            )
            assert off.status_code == 200
            route = _routes(client, admin_token)["job_portrait"]
            assert route["source"] == "env"
            assert route["warning"] and "禁用" in route["warning"]
            assert get_llm_gateway().resolve_function_key("job_portrait") is None
        finally:
            client.put(
                f"/api/v1/admin/system/models/{chat_model['id']}",
                json={"enabled": True},
                headers=_headers(admin_token),
            )
            assert _bind(client, admin_token, "job_portrait", None).status_code == 200

    def test_default_route_switches_current_model(self, client, admin_token, provider, chat_model):
        key = f"{provider['name']}:{chat_model['model_name']}"
        try:
            assert _bind(client, admin_token, "default", chat_model["id"]).status_code == 200
            assert get_llm_gateway().current_model == key
        finally:
            assert _bind(client, admin_token, "default", None).status_code == 200

        # 解绑后 default 路由消失：②（2026-09-25 决策）起不再"取第一个可用模型"，
        # 未绑 default = 没有默认模型（env 的 llm_default_model 只在 DB 完全没配置时生效）
        snapshot = get_registry_snapshot()
        assert snapshot is not None and snapshot.default_gateway_key is None
        assert "default" not in get_llm_gateway().list_function_routes()
        assert get_llm_gateway().current_model == ""  # 页面所述 = 网关真实行为


# ── 连通性测试 ──────────────────────────────────────────────────────────────


class TestConnectivity:
    def test_chat_model_failure_returns_reason(self, client, admin_token, chat_model):
        resp = client.post(
            f"/api/v1/admin/system/models/{chat_model['id']}/test", headers=_headers(admin_token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is False  # 假地址必然连不上
        assert data["kind"] == "chat"
        assert data["detail"]
        assert data["latency_ms"] >= 0

    def test_embedding_network_failure_reports_reason(self, client, admin_token, embed_model):
        resp = client.post(
            f"/api/v1/admin/system/models/{embed_model['id']}/test", headers=_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["kind"] == "embedding"
        assert data["detail"]

    def _make_model(self, client, admin_token, provider, name, dim):
        resp = client.post(
            "/api/v1/admin/system/models",
            json={
                "provider_id": provider["id"],
                "model_name": name,
                "kind": "embedding",
                "dim": dim,
            },
            headers=_headers(admin_token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _patch_embeddings(self, monkeypatch, dim: int):
        class _FakeEmbeddings:
            async def aembed_documents(self, texts):
                return [[0.0] * dim for _ in texts]

        monkeypatch.setattr(
            "app.api.v1.admin.system.build_embeddings", lambda **kwargs: _FakeEmbeddings()
        )

    def test_embedding_dim_match_is_ok(self, client, admin_token, provider, monkeypatch):
        self._patch_embeddings(monkeypatch, 1024)
        model = self._make_model(client, admin_token, provider, "embed-ok", 1024)
        data = client.post(
            f"/api/v1/admin/system/models/{model['id']}/test", headers=_headers(admin_token)
        ).json()
        assert data["ok"] is True
        assert data["dim"] == 1024
        assert data["dim_expected"] == 1024

    def test_embedding_dim_mismatch_with_vector_column(self, client, admin_token, provider, monkeypatch):
        """返回 768 维 → 与 DB 的 vector(1024) 不符，必须报 not ok（入库会失败）。"""
        self._patch_embeddings(monkeypatch, 768)
        model = self._make_model(client, admin_token, provider, "embed-768", 768)
        data = client.post(
            f"/api/v1/admin/system/models/{model['id']}/test", headers=_headers(admin_token)
        ).json()
        assert data["ok"] is False
        assert data["dim"] == 768
        assert data["dim_expected"] == 1024
        assert "1024" in data["detail"]

    def test_declared_dim_mismatch_flagged(self, client, admin_token, provider, monkeypatch):
        """实际 1024 但模型里声明 512 → 也报 not ok 并在 detail 里指出。"""
        self._patch_embeddings(monkeypatch, 1024)
        model = self._make_model(client, admin_token, provider, "embed-declared-512", 512)
        data = client.post(
            f"/api/v1/admin/system/models/{model['id']}/test", headers=_headers(admin_token)
        ).json()
        assert data["ok"] is False
        assert "512" in data["detail"]

    def test_model_without_api_key_reports_clearly(self, client, admin_token):
        prov = client.post(
            "/api/v1/admin/system/providers",
            json={"name": f"{_PREFIX}_nokey", "base_url": _BOGUS_BASE_URL},
            headers=_headers(admin_token),
        ).json()
        created = client.post(
            "/api/v1/admin/system/models",
            json={"provider_id": prov["id"], "model_name": "nokey-model", "kind": "chat"},
            headers=_headers(admin_token),
        ).json()
        resp = client.post(
            f"/api/v1/admin/system/models/{created['id']}/test", headers=_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "api_key" in data["detail"]

    def test_unknown_model_404(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/system/models/99999999/test", headers=_headers(admin_token)
        )
        assert resp.status_code == 404


# ── B4-1：简历解析 / embedding 的配置来源切换 ────────────────────────────────


class TestB41Wiring:
    def test_routes_expose_wired_flag(self, client, admin_token):
        routes = _routes(client, admin_token)
        # B3-2 起 `job_link_extract` 的调用点已接（`core/link_enrich/llm_extract.py`）
        # → 不再是"可绑定但不生效"。**绑定它不等于会调用**：链接富化的 LLM 层还有
        # 自己的开关 `LINK_ENRICH_LLM_ENABLED`（默认关）。
        assert routes["job_link_extract"]["wired"] is True
        for key in (
            "default",
            "job_quality",
            "job_extract",
            "job_portrait",
            "job_link_extract",
            "resume_parse",
            "embedding",
        ):
            assert routes[key]["wired"] is True, key

    def test_bind_resume_parse_is_effective(self, client, admin_token, provider, chat_model):
        key = f"{provider['name']}:{chat_model['model_name']}"
        try:
            resp = _bind(client, admin_token, "resume_parse", chat_model["id"])
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["source"] == "db"
            assert body["effective"] == key
            assert body["warning"] is None
            assert get_llm_gateway().resolve_function_key("resume_parse") == key
        finally:
            assert _bind(client, admin_token, "resume_parse", None).status_code == 200

        assert get_llm_gateway().resolve_function_key("resume_parse") is None

    def test_unwired_route_binds_but_warns(self, client, admin_token, chat_model, monkeypatch):
        """「可绑定但未接线」这条**机制**仍要覆盖 —— 将来加新键还会经过这个阶段。

        现在没有永久 `wired=False` 的键了（`job_link_extract` 已被 B3-2 接上），
        所以把某个键临时标成未接线来测这条路径，而不是留着生产代码里的假状态。
        """
        import app.api.v1.admin.system as system_module
        from app.core.llm.registry import FUNCTION_KEYS, FunctionKeyMeta

        def _unwire(meta: FunctionKeyMeta) -> FunctionKeyMeta:
            return FunctionKeyMeta(
                meta.key, meta.label, meta.kind, meta.fallback,
                wired=False, env_setting=meta.env_setting,
            )

        patched = tuple(
            _unwire(m) if m.key == "job_link_extract" else m for m in FUNCTION_KEYS
        )
        # ⚠️ 两个都要打：列表端点用 `FUNCTION_KEYS`，绑定端点用 `FUNCTION_KEY_MAP`
        # （`wired` 来自后者，只改前者的话绑定响应仍然会说"已接线"）
        monkeypatch.setattr(system_module, "FUNCTION_KEYS", patched)
        monkeypatch.setattr(
            system_module,
            "FUNCTION_KEY_MAP",
            {m.key: m for m in patched},
        )

        try:
            resp = _bind(client, admin_token, "job_link_extract", chat_model["id"])
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["wired"] is False
            assert body["warning"] and "尚未接入" in body["warning"]
        finally:
            assert _bind(client, admin_token, "job_link_extract", None).status_code == 200

    def test_unbound_default_reports_no_default(self, client, admin_token, provider, chat_model):
        """② 后：DB 有模型但未绑 default → 页面必须说"没有默认模型"，且网关真的没有。

        改前语义是「运行时取第一个 DB 模型」，由用户 2026-09-25 决策② 取消。
        """
        model_name = chat_model["model_name"]
        routes = _routes(client, admin_token)
        assert routes["default"]["source"] == "env"  # 没绑就是没绑
        assert "未绑 default" in routes["default"]["effective"]
        assert model_name not in routes["default"]["effective"]
        assert model_name not in routes["job_quality"]["effective"]
        assert get_llm_gateway().current_model == ""  # 页面所述 = 网关真实行为

    def test_embedding_route_feeds_get_embeddings(self, client, admin_token, embed_model, monkeypatch):
        """绑定 embedding 路由后，get_embeddings() 构造参数应换成 DB 里的模型。"""
        captured: dict[str, str] = {}

        def fake_build_embeddings(*, model: str, api_key: str, base_url: str):
            captured.update(model=model, api_key=api_key, base_url=base_url)

            class _Client:
                async def aembed_query(self, text):
                    return [0.0] * 1024

            return _Client()

        monkeypatch.setattr("app.core.llm.embeddings.build_embeddings", fake_build_embeddings)
        try:
            assert _bind(client, admin_token, "embedding", embed_model["id"]).status_code == 200
            get_embeddings()
            assert captured["model"] == embed_model["model_name"]
        finally:
            assert _bind(client, admin_token, "embedding", None).status_code == 200
            clear_embeddings_cache()
