"""LLM 网关模块公开 API。"""

from app.core.llm.embeddings import clear_embeddings_cache, get_embeddings
from app.core.llm.gateway import (
    AllProvidersFailedError,
    LLMGateway,
    LLMGatewayError,
    UnknownModelError,
    clear_gateway_cache,
    get_llm_gateway,
)
from app.core.llm.models import (
    LLMProviderConfig,
    build_provider_configs,
    create_chat_model,
)
from app.core.llm.registry import (
    FUNCTION_KEY_MAP,
    FUNCTION_KEYS,
    FunctionKeyMeta,
    RegistrySnapshot,
    RouteSpec,
    get_registry_snapshot,
    invalidate_llm_registry,
    load_snapshot,
    reload_registry,
    resolve_route,
)
from app.core.llm.secrets import decrypt_secret, encrypt_secret, mask_secret

__all__ = [
    "FUNCTION_KEYS",
    "FUNCTION_KEY_MAP",
    "AllProvidersFailedError",
    "FunctionKeyMeta",
    "LLMGateway",
    "LLMGatewayError",
    "LLMProviderConfig",
    "RegistrySnapshot",
    "RouteSpec",
    "UnknownModelError",
    "build_provider_configs",
    "clear_embeddings_cache",
    "clear_gateway_cache",
    "create_chat_model",
    "decrypt_secret",
    "encrypt_secret",
    "get_embeddings",
    "get_llm_gateway",
    "get_registry_snapshot",
    "invalidate_llm_registry",
    "load_snapshot",
    "mask_secret",
    "reload_registry",
    "resolve_route",
]
