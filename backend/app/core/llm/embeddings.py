from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import get_settings


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """构建 embedding 客户端。

    优先级：通用 EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL
    → 回退 SiliconFlow 兼容配置（SILICONFLOW_*）。

    ⚠️ 数据库 embedding 列固定为 vector(1024)：更换 provider 后必须确认
    其输出维度为 1024，否则 pgvector 插入会失败（岗位向量写不进去）。
    """
    settings = get_settings()

    api_key = (settings.embedding_api_key or settings.siliconflow_api_key or "").strip()
    base_url = (
        settings.embedding_base_url or settings.siliconflow_base_url or ""
    ).strip()
    model = (
        settings.embedding_model or settings.siliconflow_embedding_model or ""
    ).strip()

    return OpenAIEmbeddings(
        model=model,
        api_key=api_key,
        base_url=base_url,
        # 兼容性必需：默认 True 时 langchain 会在本地把文本分词成 token 数组再发给
        # /embeddings，阿里云百炼(DashScope)等只接受 str / list[str]，会返回
        # 400 InvalidParameter: contents is neither str nor list of str。
        check_embedding_ctx_length=False,
    )
