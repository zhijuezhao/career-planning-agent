from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.config import get_settings
from app.core.llm.embeddings import VECTOR_DIM, build_embeddings
from app.core.llm.models import LLMProviderConfig, create_chat_model
from app.core.llm.registry import (
    FUNCTION_KEY_MAP,
    FUNCTION_KEYS,
    FunctionKeyMeta,
    get_registry_snapshot,
    invalidate_llm_registry,
    reload_registry,
    resolve_env_model,
)
from app.core.llm.secrets import decrypt_secret, encrypt_secret, mask_secret
from app.domain.models.llm_config import LLMModel, LLMProvider, LLMRoute
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    FunctionRouteListResponse,
    FunctionRouteResponse,
    FunctionRouteUpdate,
    LLMConnectivityTestResponse,
    LLMModelCreate,
    LLMModelListResponse,
    LLMModelResponse,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderListResponse,
    LLMProviderResponse,
    LLMProviderUpdate,
)

router = APIRouter()


# ── Scheduler Status ────────────────────────────────────────────────────────


@router.get("/scheduler/status")
async def get_scheduler_status(
    current_user: User = Depends(require_admin),
):
    """Get the status of the adaptive scheduler."""
    from app.main import app

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return {"status": "not_initialized", "jobs": []}

    return {
        "status": "running" if scheduler._scheduler.running else "stopped",
        "jobs": scheduler.get_job_info(),
    }


# ── LLM 配置中心（B2-1）：供应商 / 模型 / 功能路由 / 连通性测试 ────────────────
#
# 热生效机制：任何写操作后 `_touch_llm_registry()` 重建 DB 快照并清掉网关/向量单例，
# 下一次 LLM 调用即使用新配置 —— 不需要重启后端。
# DB 一张表都没配时，网关行为与接入前完全一致（回退 env）。


async def _touch_llm_registry(db: AsyncSession) -> None:
    await db.flush()
    await reload_registry(db)
    invalidate_llm_registry()


def _provider_response(provider: LLMProvider, model_count: int = 0) -> LLMProviderResponse:
    plain = decrypt_secret(provider.api_key_encrypted)
    return LLMProviderResponse(
        id=provider.id,
        name=provider.name,
        base_url=provider.base_url,
        enabled=provider.enabled,
        sort_order=provider.sort_order,
        api_key_set=bool(provider.api_key_encrypted),
        api_key_masked=mask_secret(plain),
        model_count=model_count,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _model_response(model: LLMModel, provider_name: str | None = None) -> LLMModelResponse:
    return LLMModelResponse(
        id=model.id,
        provider_id=model.provider_id,
        provider_name=provider_name,
        model_name=model.model_name,
        display_name=model.display_name,
        kind=model.kind,
        dim=model.dim,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        enabled=model.enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


async def _get_provider(db: AsyncSession, provider_id: int) -> LLMProvider:
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return provider


async def _get_model(db: AsyncSession, model_id: int) -> LLMModel:
    model = await db.get(LLMModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    return model


# ── 供应商 ──────────────────────────────────────────────────────────────────


@router.get("/providers", response_model=LLMProviderListResponse)
async def list_llm_providers(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """供应商列表（api_key 只回掩码）。"""
    providers = list(
        (
            await db.execute(
                select(LLMProvider).order_by(LLMProvider.sort_order, LLMProvider.id)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                select(LLMModel.provider_id, func.count()).group_by(LLMModel.provider_id)
            )
        ).all()
    )
    return LLMProviderListResponse(
        total=len(providers),
        items=[_provider_response(p, counts.get(p.id, 0)) for p in providers],
    )


@router.post("/providers", response_model=LLMProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_provider(
    data: LLMProviderCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """新建供应商；api_key 加密落库（明文永不入库）。"""
    existing = (
        await db.execute(select(LLMProvider).where(LLMProvider.name == data.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="LLM provider with this name already exists")

    provider = LLMProvider(
        name=data.name,
        base_url=data.base_url,
        enabled=data.enabled,
        sort_order=data.sort_order,
        api_key_encrypted=encrypt_secret(data.api_key) if data.api_key else None,
    )
    db.add(provider)
    await _touch_llm_registry(db)
    await db.refresh(provider)
    return _provider_response(provider)


@router.put("/providers/{provider_id}", response_model=LLMProviderResponse)
async def update_llm_provider(
    provider_id: int,
    data: LLMProviderUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """改供应商。`api_key` 不传=不改，传空串=清除密钥。"""
    provider = await _get_provider(db, provider_id)
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] != provider.name:
        dup = (
            await db.execute(select(LLMProvider).where(LLMProvider.name == fields["name"]))
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=409, detail="LLM provider with this name already exists")
        provider.name = fields.pop("name")
    else:
        fields.pop("name", None)

    if "api_key" in fields:
        api_key = fields.pop("api_key")
        provider.api_key_encrypted = encrypt_secret(api_key) if api_key else None

    for field, value in fields.items():
        setattr(provider, field, value)

    await _touch_llm_registry(db)
    await db.refresh(provider)
    counts = dict(
        (
            await db.execute(
                select(LLMModel.provider_id, func.count()).group_by(LLMModel.provider_id)
            )
        ).all()
    )
    return _provider_response(provider, counts.get(provider.id, 0))


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider(
    provider_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除供应商（其下模型与相关功能路由由 DB 外键级联删除）。"""
    provider = await _get_provider(db, provider_id)
    await db.delete(provider)
    await _touch_llm_registry(db)


# ── 模型 ────────────────────────────────────────────────────────────────────


@router.get("/models", response_model=LLMModelListResponse)
async def list_llm_models(
    provider_id: int | None = None,
    kind: str | None = Query(None, pattern="^(chat|embedding)$"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """模型列表（可按供应商与类型过滤）。"""
    query = select(LLMModel).order_by(LLMModel.provider_id, LLMModel.id)
    if provider_id is not None:
        query = query.where(LLMModel.provider_id == provider_id)
    if kind is not None:
        query = query.where(LLMModel.kind == kind)
    models = list((await db.execute(query)).scalars().all())
    providers = {
        p.id: p.name for p in (await db.execute(select(LLMProvider))).scalars().all()
    }
    return LLMModelListResponse(
        total=len(models),
        items=[_model_response(m, providers.get(m.provider_id)) for m in models],
    )


@router.post("/models", response_model=LLMModelResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_model(
    data: LLMModelCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """新建模型（同一供应商下 model_name 唯一）。"""
    provider = await _get_provider(db, data.provider_id)
    dup = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == data.provider_id,
                LLMModel.model_name == data.model_name,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="This model already exists under the provider")

    model = LLMModel(
        provider_id=data.provider_id,
        model_name=data.model_name,
        display_name=data.display_name,
        kind=data.kind,
        dim=data.dim,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        enabled=data.enabled,
    )
    db.add(model)
    await _touch_llm_registry(db)
    await db.refresh(model)
    return _model_response(model, provider.name)


@router.put("/models/{model_id}", response_model=LLMModelResponse)
async def update_llm_model(
    model_id: int,
    data: LLMModelUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """改模型（名称、类型、维度、采样参数、启停）。"""
    model = await _get_model(db, model_id)
    fields = data.model_dump(exclude_unset=True)

    new_name = fields.get("model_name")
    if new_name is not None and new_name != model.model_name:
        dup = (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.provider_id == model.provider_id,
                    LLMModel.model_name == new_name,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=409, detail="This model already exists under the provider"
            )

    for field, value in fields.items():
        setattr(model, field, value)

    await _touch_llm_registry(db)
    provider = await db.get(LLMProvider, model.provider_id)
    await db.refresh(model)
    return _model_response(model, provider.name if provider else None)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_model(
    model_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除模型（相关功能路由由 DB 外键级联删除）。"""
    model = await _get_model(db, model_id)
    await db.delete(model)
    await _touch_llm_registry(db)


# ── 功能路由 ────────────────────────────────────────────────────────────────


#: 未绑定 `default` 时的显示口径。必须与 `gateway.NO_DEFAULT_MODEL_HINT` 同义：
#: 2026-09-25（用户决策②）起，DB 里有模型**不再**自动接管默认。
_NO_DEFAULT_LABEL = "无默认模型（未绑定 default）"


def _runtime_default_hint() -> str:
    """运行时真正生效的默认模型名。

    ② 之前：DB 一旦有可用 chat 模型（且未绑 `default`），网关取第一个 DB 模型 →
    页面得跟着说"取第一个可用模型"。
    ② 之后：**只有显式绑定 `default` 才有默认模型**；没绑就是没有，页面必须如实显示
    （否则管理员会以为还有兜底，实际调用会直接报错）。
    """
    snapshot = get_registry_snapshot()
    if snapshot is not None and snapshot.chat_configs:
        return snapshot.default_gateway_key or _NO_DEFAULT_LABEL
    return get_settings().llm_default_model


def _env_effective(meta: FunctionKeyMeta) -> str:
    settings = get_settings()
    if meta.kind == "embedding":
        fallback_model = settings.embedding_model or settings.siliconflow_embedding_model
        return f"env EMBEDDING_*（当前：{fallback_model or '未配置'}）"
    env_model = resolve_env_model(meta.key)  # 目前仅 resume_parse 有（B4-1）
    if env_model:
        return f"env {meta.env_setting}（当前：{env_model}）"
    snapshot = get_registry_snapshot()
    db_default = snapshot is not None and bool(snapshot.chat_configs)
    if meta.key == "default":
        if db_default:
            return f"未绑 default → {_NO_DEFAULT_LABEL}，需显式绑定"
        return f"env llm_default_model（当前：{settings.llm_default_model}）"
    return f"跟随 default（当前：{_runtime_default_hint()}）"


def _route_response(
    meta: FunctionKeyMeta,
    route: LLMRoute | None,
    model: LLMModel | None,
    provider: LLMProvider | None,
) -> FunctionRouteResponse:
    """按与 registry.load_snapshot 完全相同的规则判断该功能键是否真的生效。"""
    bound_model = (
        f"{provider.name}:{model.model_name}" if model is not None and provider is not None else None
    )
    warning: str | None = None
    # 可绑定但调用点还没接：配置是「存下来」了，但不能说它生效
    unwired_warning = "调用点尚未接入（B3-2 链接解析才用到），绑定暂不生效" if not meta.wired else None

    if route is None:
        pass  # 未配置 → env
    elif model is None or provider is None:
        warning = "绑定的模型/供应商已不存在"
    elif not provider.enabled:
        warning = f"供应商 {provider.name} 已禁用"
    elif not model.enabled:
        warning = f"模型 {model.model_name} 已禁用"
    elif meta.kind != model.kind:
        warning = f"kind 不符：该功能键要求 {meta.kind}，绑定的是 {model.kind}"
    elif not decrypt_secret(provider.api_key_encrypted):
        warning = f"供应商 {provider.name} 未配置有效 api_key"
    else:
        return FunctionRouteResponse(
            function_key=meta.key,
            label=meta.label,
            kind=meta.kind,
            wired=meta.wired,
            bound_model_id=model.id,
            bound_model=bound_model,
            source="db",
            effective=bound_model or "",
            fallback=meta.fallback,
            warning=unwired_warning,
            updated_at=route.updated_at,
        )

    if warning is None and route is not None:
        warning = "配置未生效"

    return FunctionRouteResponse(
        function_key=meta.key,
        label=meta.label,
        kind=meta.kind,
        wired=meta.wired,
        bound_model_id=model.id if model is not None else None,
        bound_model=bound_model,
        source="env",
        effective=_env_effective(meta),
        fallback=meta.fallback,
        warning=warning or unwired_warning,
        updated_at=route.updated_at if route is not None else None,
    )


@router.get("/routes", response_model=FunctionRouteListResponse)
async def list_llm_routes(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """功能键 → 模型 的绑定总览（含「当前生效」与「来源：DB/env」）。"""
    routes = {r.function_key: r for r in (await db.execute(select(LLMRoute))).scalars().all()}
    models = {m.id: m for m in (await db.execute(select(LLMModel))).scalars().all()}
    providers = {p.id: p for p in (await db.execute(select(LLMProvider))).scalars().all()}

    items = []
    for meta in FUNCTION_KEYS:
        route = routes.get(meta.key)
        model = models.get(route.model_id) if route is not None else None
        provider = providers.get(model.provider_id) if model is not None else None
        items.append(_route_response(meta, route, model, provider))
    return FunctionRouteListResponse(total=len(items), items=items)


@router.put("/routes/{function_key}", response_model=FunctionRouteResponse)
async def bind_llm_route(
    function_key: str,
    data: FunctionRouteUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """绑定 / 解绑功能键（`model_id: null` = 解绑回 env）。绑定后立即生效。"""
    meta = FUNCTION_KEY_MAP.get(function_key)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown function_key '{function_key}'. Known: {sorted(FUNCTION_KEY_MAP)}",
        )

    route = (
        await db.execute(select(LLMRoute).where(LLMRoute.function_key == function_key))
    ).scalar_one_or_none()

    if data.model_id is None:
        if route is not None:
            await db.delete(route)
        await _touch_llm_registry(db)
        return _route_response(meta, None, None, None)

    model = await _get_model(db, data.model_id)
    if model.kind != meta.kind:
        raise HTTPException(
            status_code=409,
            detail=f"Function '{function_key}' requires kind={meta.kind}, got {model.kind}",
        )

    if route is None:
        route = LLMRoute(function_key=function_key, model_id=model.id)
        db.add(route)
    else:
        route.model_id = model.id

    await _touch_llm_registry(db)
    provider = await db.get(LLMProvider, model.provider_id)
    await db.refresh(route)
    return _route_response(meta, route, model, provider)


# ── 连通性测试 ──────────────────────────────────────────────────────────────


@router.post("/models/{model_id}/test", response_model=LLMConnectivityTestResponse)
async def test_llm_model(
    model_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """真实调用一次：chat 发最小 ping；embedding 对短文本取向量并核对维度。

    只读操作，不改任何配置；失败也返回 200 + ok=false（便于前端直接展示原因）。
    """
    model = await _get_model(db, model_id)
    provider = await db.get(LLMProvider, model.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")

    api_key = decrypt_secret(provider.api_key_encrypted)
    base_url = (provider.base_url or "").strip()
    started = time.perf_counter()

    if not api_key:
        return LLMConnectivityTestResponse(
            ok=False,
            model=model.model_name,
            kind=model.kind,
            latency_ms=0,
            detail=f"供应商 {provider.name} 未配置 api_key（可先保存密钥再测试）",
        )

    try:
        if model.kind == "embedding":
            client = build_embeddings(
                model=model.model_name, api_key=api_key, base_url=base_url
            )
            vectors = await client.aembed_documents(["连通性测试"])
            actual = len(vectors[0]) if vectors else 0
            latency_ms = int((time.perf_counter() - started) * 1000)
            # 判定基准固定是 DB 向量列维度：模型里声明得再"对"，与 vector(1024) 不一致也会写库失败
            ok = actual == VECTOR_DIM
            detail = (
                f"嵌入维度 {actual}，与 DB 向量列 vector({VECTOR_DIM}) 一致"
                if ok
                else f"嵌入维度 {actual}，与 DB 向量列 vector({VECTOR_DIM}) 不一致（入库会失败）"
            )
            if model.dim is not None and model.dim != actual:
                ok = False
                detail += f"；模型声明的 dim={model.dim} 与实际返回不符"
            return LLMConnectivityTestResponse(
                ok=ok,
                model=model.model_name,
                kind=model.kind,
                latency_ms=latency_ms,
                dim=actual,
                dim_expected=VECTOR_DIM,
                detail=detail,
            )

        cfg = LLMProviderConfig(
            name=f"{provider.name}:{model.model_name}",
            api_key=SecretStr(api_key),
            base_url=base_url,
            model_name=model.model_name,
            temperature=0.0,
            max_tokens=16,
            streaming=False,
            request_timeout=15,
            max_retries=0,
        )
        response = await create_chat_model(cfg).ainvoke("ping")
        content = response.content if isinstance(response.content, str) else str(response.content)
        return LLMConnectivityTestResponse(
            ok=True,
            model=model.model_name,
            kind=model.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            output_preview=content[:200],
            detail="调用成功",
        )
    except Exception as exc:  # noqa: BLE001 - 连通性测试要把任何失败原因回给管理员
        return LLMConnectivityTestResponse(
            ok=False,
            model=model.model_name,
            kind=model.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=f"{type(exc).__name__}: {exc}"[:400],
        )
