from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "career-planning-agent"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_planning"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-to-a-random-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # LLM - DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # LLM - Qwen
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    # LLM - LongCat
    longcat_api_key: str = ""
    longcat_base_url: str = "https://api.longcat.chat/openai"
    longcat_model: str = "LongCat-2.0"

    # Embedding - 可配置 provider（EMBEDDING_* 优先；留空则回退 SiliconFlow 兼容配置）
    # 数据库列固定为 vector(1024)，切换 provider 时必须确认输出维度为 1024。
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""

    # Embedding - SiliconFlow（兼容回退）
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "Qwen/Qwen3-Embedding-8B"

    # LLM Gateway
    llm_default_model: str = "deepseek"
    llm_fallback_order: str = "deepseek,qwen"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096
    llm_request_timeout: int = 60

    # LangSmith
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "career-planning-agent"

    # File storage
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10

    # Resume parsing
    resume_max_text_chars: int = 15000
    resume_llm_model: str | None = None

    # Web search - Tavily
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
