"""功能键 → 模型 的运行时注册表（B2-1「改配置不重启即生效」的核心）。

数据流：
    DB(llm_providers/llm_models/llm_routes) --reload_registry(session)--> RegistrySnapshot
        --> 进程内缓存（本模块的模块级快照）
        --> LLMGateway（chat 模型表 + 功能路由）/ get_embeddings（embedding）

为什么用「快照 + 显式重建」而不是每次查库：
    * 热路径（每次 LLM 调用）不碰数据库、不进 async 上下文，避免把 DB 会话带进
      LangGraph 节点与同步上下文；
    * 保存配置的端点在同一请求内 `await reload_registry(db)` 后调
      `invalidate_llm_registry()` 清掉网关/向量单例，下一次调用即用新配置 —— 无需重启。

**DB 为空时的行为与接入前完全一致**：快照里 chat_configs 为空 → 网关回退 env
`build_provider_configs()`，embedding 回退 env `EMBEDDING_*` → SiliconFlow。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.llm.models import LLMProviderConfig
from app.core.llm.secrets import decrypt_secret
from app.domain.models.llm_config import LLMModel, LLMProvider, LLMRoute

# ── 功能键清单（唯一事实来源：后端接口把它暴露给前端渲染）──────────────────────


@dataclass(frozen=True)
class FunctionKeyMeta:
    key: str
    label: str
    kind: str  # chat | embedding
    fallback: str  # 未配置时的回退说明（前端「来源：DB/env」展示用）
    wired: bool = True  # 调用点是否已接入（False = 可绑定但暂不生效，界面会提示）
    env_setting: str | None = None  # 未绑定时可回退的 env 配置项名（如 resume_llm_model）


FUNCTION_KEYS: tuple[FunctionKeyMeta, ...] = (
    FunctionKeyMeta("default", "默认（兜底）", "chat", "env llm_default_model"),
    FunctionKeyMeta("job_quality", "导入-质检", "chat", "default"),
    FunctionKeyMeta("job_extract", "导入-结构化提取", "chat", "default"),
    FunctionKeyMeta("job_portrait", "导入-画像", "chat", "default"),
    # B3-2 已接上调用点：链接富化 L3（`core/link_enrich/llm_extract.py`）用它调模型。
    # ⚠️ 该层还有**自己的开关** `LINK_ENRICH_LLM_ENABLED`（默认关）+ 调用数/token 预算：
    # 这里绑定了模型、但开关没开时依然一次都不会调用。
    FunctionKeyMeta("job_link_extract", "链接字段解析（LLM + XPath）", "chat", "default"),
    # B4-1：未绑定时回退 env `resume_llm_model`（历史配置项，此前从未被读取）
    FunctionKeyMeta(
        "resume_parse",
        "简历解析",
        "chat",
        "env resume_llm_model → default",
        env_setting="resume_llm_model",
    ),
    FunctionKeyMeta("embedding", "向量模型", "embedding", "env EMBEDDING_* → SiliconFlow"),
)

FUNCTION_KEY_MAP: dict[str, FunctionKeyMeta] = {meta.key: meta for meta in FUNCTION_KEYS}


def resolve_env_model(function_key: str | None) -> str | None:
    """功能键未绑 DB 时可回退的 env 模型名（网关内的模型 key，如 "qwen"）。

    目前只有 `resume_parse` 有这类历史配置（`settings.resume_llm_model`）。
    返回的名字**不保证**在当前网关注册表里存在，调用方需再校验。
    """
    if not function_key:
        return None
    meta = FUNCTION_KEY_MAP.get(function_key)
    if meta is None or not meta.env_setting:
        return None
    value = getattr(get_settings(), meta.env_setting, None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def gateway_key(provider_name: str, model_name: str) -> str:
    """网关内模型唯一键（供应商名 + 模型名，避免不同供应商同名模型互撞）。"""
    return f"{provider_name}:{model_name}"


# ── 快照 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteSpec:
    """一条「功能键 → 模型」绑定的解析结果（api_key 已解密）。"""

    function_key: str
    provider_id: int
    provider_name: str
    model_id: int
    model_name: str
    kind: str
    base_url: str
    api_key: str
    temperature: float
    max_tokens: int
    dim: int | None

    @property
    def gateway_key(self) -> str:
        return gateway_key(self.provider_name, self.model_name)

    @property
    def label(self) -> str:
        return self.gateway_key


@dataclass(frozen=True)
class RegistrySnapshot:
    version: int
    loaded_at: datetime
    routes: dict[str, RouteSpec] = field(default_factory=dict)
    chat_configs: dict[str, LLMProviderConfig] = field(default_factory=dict)
    fallback_order: tuple[str, ...] = ()
    chat_labels: dict[str, str] = field(default_factory=dict)

    @property
    def default_gateway_key(self) -> str | None:
        spec = self.routes.get("default")
        return spec.gateway_key if spec else None

    @property
    def embedding(self) -> RouteSpec | None:
        spec = self.routes.get("embedding")
        return spec if spec is not None and spec.kind == "embedding" else None

    @property
    def source(self) -> str:
        """chat 模型来源：DB（有配置）还是 env 回退。"""
        return "db" if self.chat_configs else "env"


_state_lock = threading.Lock()
_snapshot: RegistrySnapshot | None = None
_version = 0


def get_registry_snapshot() -> RegistrySnapshot | None:
    """当前快照（可能为 None = 尚未加载）。同步、无 IO，可在任意热路径调用。"""
    return _snapshot


def resolve_route(function_key: str | None) -> RouteSpec | None:
    """按功能键取绑定；未配置返回 None（调用方回退默认模型）。"""
    if not function_key:
        return None
    snapshot = _snapshot
    if snapshot is None:
        return None
    return snapshot.routes.get(function_key)


def get_registry_chat_configs() -> dict[str, LLMProviderConfig]:
    snapshot = _snapshot
    return dict(snapshot.chat_configs) if snapshot else {}


def set_registry_snapshot(snapshot: RegistrySnapshot | None) -> None:
    """直接替换快照（测试与启动预热用）。"""
    global _snapshot
    with _state_lock:
        _snapshot = snapshot


def clear_registry_snapshot() -> None:
    """清空快照（测试隔离用；生产流程请用 reload_registry + invalidate）。"""
    set_registry_snapshot(None)


# ── 构建 ────────────────────────────────────────────────────────────────────


async def load_snapshot(session: AsyncSession, version: int = 0) -> RegistrySnapshot:
    """从 DB 构建快照（不改模块状态，便于测试与 dry-run）。"""
    settings = get_settings()

    providers = {p.id: p for p in (await session.execute(select(LLMProvider))).scalars()}
    models = {m.id: m for m in (await session.execute(select(LLMModel))).scalars()}
    routes = list((await session.execute(select(LLMRoute))).scalars())

    chat_configs: dict[str, LLMProviderConfig] = {}
    chat_labels: dict[str, str] = {}
    ordered: list[tuple[int, int, str]] = []

    for model in models.values():
        provider = providers.get(model.provider_id)
        if provider is None or not provider.enabled or not model.enabled:
            continue
        api_key = decrypt_secret(provider.api_key_encrypted)
        if not api_key:
            # 与 env 行为一致：无密钥的供应商不进网关（否则只会返回 401）
            logger.warning("供应商 {!r} 的模型 {!r} 未配置可用 api_key，已跳过", provider.name, model.model_name)
            continue
        key = gateway_key(provider.name, model.model_name)
        if model.kind != "chat":
            continue
        chat_configs[key] = LLMProviderConfig(
            name=key,
            api_key=SecretStr(api_key),
            base_url=(provider.base_url or "").strip(),
            model_name=model.model_name,
            temperature=model.temperature if model.temperature is not None else settings.llm_temperature,
            max_tokens=model.max_tokens or settings.llm_max_tokens,
            streaming=True,
            request_timeout=settings.llm_request_timeout,
        )
        chat_labels[key] = model.display_name or model.model_name
        ordered.append((provider.sort_order, model.id, key))

    # 供应商 sort_order 优先，其次按模型 id（稳定序）
    fallback_order = tuple(key for _, _, key in sorted(ordered))

    route_specs: dict[str, RouteSpec] = {}
    for route in routes:
        meta = FUNCTION_KEY_MAP.get(route.function_key)
        if meta is None:
            logger.warning("忽略未知功能键 {!r}", route.function_key)
            continue
        model = models.get(route.model_id)
        provider = providers.get(model.provider_id) if model is not None else None
        if model is None or provider is None:
            continue
        if not provider.enabled or not model.enabled:
            continue
        if meta.kind != model.kind:
            logger.warning(
                "功能键 {!r} 期望 kind={}，但绑定模型是 {}，已忽略（请在管理端改绑）",
                route.function_key,
                meta.kind,
                model.kind,
            )
            continue
        api_key = decrypt_secret(provider.api_key_encrypted)
        if not api_key:
            continue
        route_specs[route.function_key] = RouteSpec(
            function_key=route.function_key,
            provider_id=provider.id,
            provider_name=provider.name,
            model_id=model.id,
            model_name=model.model_name,
            kind=model.kind,
            base_url=(provider.base_url or "").strip(),
            api_key=api_key,
            temperature=model.temperature if model.temperature is not None else settings.llm_temperature,
            max_tokens=model.max_tokens or settings.llm_max_tokens,
            dim=model.dim,
        )

    return RegistrySnapshot(
        version=version,
        loaded_at=datetime.now(timezone.utc),
        routes=route_specs,
        chat_configs=chat_configs,
        fallback_order=fallback_order,
        chat_labels=chat_labels,
    )


async def reload_registry(session: AsyncSession) -> RegistrySnapshot:
    """重建快照并替换进程内缓存。**保存/删除配置后必须调用**（随后再 invalidate）。"""
    global _snapshot, _version
    snapshot = await load_snapshot(session, version=_version + 1)
    with _state_lock:
        _version = snapshot.version
        _snapshot = snapshot
    logger.info(
        "模型配置快照已重建 | version={} | chat_models={} | routes={} | source={}",
        snapshot.version,
        len(snapshot.chat_configs),
        sorted(snapshot.routes.keys()),
        snapshot.source,
    )
    return snapshot


def invalidate_llm_registry() -> None:
    """清掉由快照派生的单例缓存：LLM 网关 + embeddings 客户端。

    注意：**不清快照本身**（清了会让网关回退 env，反而丢掉刚保存的配置）。
    调用顺序固定为：`await reload_registry(db)` → 本函数。
    """
    from app.core.llm.embeddings import clear_embeddings_cache
    from app.core.llm.gateway import clear_gateway_cache

    clear_gateway_cache()
    clear_embeddings_cache()
    logger.info("LLM 网关/向量客户端缓存已失效，下一次调用将使用最新配置")


__all__ = [
    "FUNCTION_KEYS",
    "FUNCTION_KEY_MAP",
    "FunctionKeyMeta",
    "RegistrySnapshot",
    "RouteSpec",
    "clear_registry_snapshot",
    "gateway_key",
    "get_registry_chat_configs",
    "get_registry_snapshot",
    "invalidate_llm_registry",
    "load_snapshot",
    "reload_registry",
    "resolve_env_model",
    "resolve_route",
    "set_registry_snapshot",
]
