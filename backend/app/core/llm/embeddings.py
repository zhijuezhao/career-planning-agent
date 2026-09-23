from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from loguru import logger

from app.config import get_settings
from app.core.llm.registry import get_registry_snapshot

# DB 向量列固定为 vector(1024)（job_match_embeddings / profile_snapshots.embedding）
VECTOR_DIM = 1024


def build_embeddings(model: str, api_key: str, base_url: str) -> OpenAIEmbeddings:
    """Adapter 工厂：embedding 客户端（唯一直接接触 langchain-openai 的地方）。"""
    return OpenAIEmbeddings(
        model=model,
        api_key=api_key,
        base_url=base_url,
        # 兼容性必需：默认 True 时 langchain 会在本地把文本分词成 token 数组再发给
        # /embeddings，阿里云百炼(DashScope)等只接受 str / list[str]，会返回
        # 400 InvalidParameter: contents is neither str nor list of str。
        check_embedding_ctx_length=False,
    )


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """构建 embedding 客户端。

    优先级（B2-1 起）：DB 的 `embedding` 功能路由 → env `EMBEDDING_*` → SiliconFlow 兼容配置。

    ⚠️ 数据库 embedding 列固定为 vector(1024)：更换 provider 后必须确认
    其输出维度为 1024，否则 pgvector 插入会失败（岗位向量写不进去）。
    管理端在模型里填了 `dim` 时，这里会提前告警；`POST /system/models/{id}/test`
    会实际 embed 一段文本并核对维度。
    """
    settings = get_settings()

    snapshot = get_registry_snapshot()
    spec = snapshot.embedding if snapshot is not None else None
    if spec is not None:
        if spec.dim and spec.dim != VECTOR_DIM:
            logger.warning(
                "DB 配置的 embedding 模型 {}/{} 声明 dim={}，与向量列 vector({}) 不一致，"
                "写入 pgvector 会失败",
                spec.provider_name,
                spec.model_name,
                spec.dim,
                VECTOR_DIM,
            )
        logger.info(
            "Embedding 使用 DB 配置 | {}/{} | base_url={}",
            spec.provider_name,
            spec.model_name,
            spec.base_url,
        )
        return build_embeddings(
            model=spec.model_name, api_key=spec.api_key, base_url=spec.base_url
        )

    api_key = (settings.embedding_api_key or settings.siliconflow_api_key or "").strip()
    base_url = (
        settings.embedding_base_url or settings.siliconflow_base_url or ""
    ).strip()
    model = (
        settings.embedding_model or settings.siliconflow_embedding_model or ""
    ).strip()

    return build_embeddings(model=model, api_key=api_key, base_url=base_url)


def clear_embeddings_cache() -> None:
    """清掉 embedding 单例 —— 换向量模型必须清缓存，否则仍用旧模型（B2-1）。"""
    get_embeddings.cache_clear()


__all__ = ["VECTOR_DIM", "build_embeddings", "clear_embeddings_cache", "get_embeddings"]
