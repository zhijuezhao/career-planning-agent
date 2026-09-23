from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from loguru import logger

from app.config import get_settings
from app.core.llm.registry import get_registry_snapshot

# DB 向量列固定为 vector(1024)（job_match_embeddings / profile_snapshots.embedding / career_knowledge）
VECTOR_DIM = 1024


class EmbeddingDimError(RuntimeError):
    """向量维度与 DB 列定义不符（继续走会在 pgvector 写入时报难以理解的错）。"""


def ensure_vector_dim(vector: list[float] | None, *, source: str = "embedding") -> list[float]:
    """校验向量维度；不符立刻抛 `EmbeddingDimError`（B4-1）。

    放在 embedding 出口而不是入库口：所有写入点（快照 / 岗位向量 / 知识库）共用同一个
    客户端，出口校验只需一处，且调用方原本就有 try/except 降级逻辑（如快照退化为零向量）。
    """
    if vector is None:
        raise EmbeddingDimError(f"{source} 返回空向量")
    actual = len(vector)
    if actual != VECTOR_DIM:
        raise EmbeddingDimError(
            f"{source} 返回 {actual} 维向量，但 DB 向量列固定 vector({VECTOR_DIM})。"
            f"请在「系统配置 > 模型」里改绑输出 {VECTOR_DIM} 维的向量模型，"
            f"并用「测试」核对维度后再绑定 embedding 功能键。"
        )
    return vector


class DimCheckedEmbeddings:
    """给 embedding 客户端套一层维度校验（只拦明显错配，不改变成功路径行为）。

    - `aembed_query` / `aembed_documents`：校验后再返回；
    - 其余属性/方法（同步 `embed_*`、模型名等）通过 `__getattr__` 原样透传，
      避免破坏既有调用点或未来的 vectorstore 集成。
    """

    def __init__(self, inner: OpenAIEmbeddings):
        self._inner = inner

    @property
    def inner(self) -> OpenAIEmbeddings:
        return self._inner

    async def aembed_query(self, text: str) -> list[float]:
        return ensure_vector_dim(await self._inner.aembed_query(text), source="aembed_query")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = await self._inner.aembed_documents(texts)
        for index, vector in enumerate(vectors):
            ensure_vector_dim(vector, source=f"aembed_documents[{index}]")
        return vectors

    def __getattr__(self, item: str):
        return getattr(self._inner, item)


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
def get_embeddings() -> DimCheckedEmbeddings:
    """构建 embedding 客户端。

    优先级（B2-1 起）：DB 的 `embedding` 功能路由 → env `EMBEDDING_*` → SiliconFlow 兼容配置。

    ⚠️ 数据库 embedding 列固定为 vector(1024)：更换 provider 后必须确认
    其输出维度为 1024。B4-1 起返回值外面套了 `DimCheckedEmbeddings`，
    维度不符会在**出口**直接抛 `EmbeddingDimError`（而不是等 pgvector 写入失败）；
    管理端 `POST /system/models/{id}/test` 可先实际 embed 一段文本核对维度。
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
        return DimCheckedEmbeddings(
            build_embeddings(model=spec.model_name, api_key=spec.api_key, base_url=spec.base_url)
        )

    api_key = (settings.embedding_api_key or settings.siliconflow_api_key or "").strip()
    base_url = (
        settings.embedding_base_url or settings.siliconflow_base_url or ""
    ).strip()
    model = (
        settings.embedding_model or settings.siliconflow_embedding_model or ""
    ).strip()

    return DimCheckedEmbeddings(build_embeddings(model=model, api_key=api_key, base_url=base_url))


def clear_embeddings_cache() -> None:
    """清掉 embedding 单例 —— 换向量模型必须清缓存，否则仍用旧模型（B2-1）。"""
    get_embeddings.cache_clear()


__all__ = [
    "VECTOR_DIM",
    "DimCheckedEmbeddings",
    "EmbeddingDimError",
    "build_embeddings",
    "clear_embeddings_cache",
    "ensure_vector_dim",
    "get_embeddings",
]
