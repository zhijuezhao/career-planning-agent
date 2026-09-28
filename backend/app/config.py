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

    # Chat agent（ReAct 循环）
    # 步数上限：LangGraph 的 recursion_limit。ReAct 每轮 = 模型调用 + 工具执行，
    # 太小会截断"多步查证"类问题，太大则可能反复调工具烧 token → 默认 12 步。
    chat_agent_recursion_limit: int = 12

    # 单次导入行数上限（原 `_import_runner.IMPORT_MAX_ROWS` 硬编码 50）。
    # 流水线每行 3 次 LLM（质检/提取/画像）→ 上限就是"误点一次最多烧多少额度"的闸门。
    # env `IMPORT_MAX_ROWS` 可覆盖，默认 100。
    import_max_rows: int = 100

    # ── Link Enrich（B3-1，零 LLM）：表格里的链接字段 → 抓取 → 结构化提取 → 合并 ──
    # 总开关默认 **false**（主计划 §4.5）：先让代码上线但不出网，验证后再打开。
    link_enrich_enabled: bool = False
    # 每次导入最多富化多少行 / 最多抓多少个唯一 URL —— 双重闸门。行数防"一次误上传
    # 刷爆目标站"，URL 数防"一个备注格里塞了 50 条链接"。
    link_enrich_max_rows: int = 20
    link_enrich_max_urls: int = 30
    # 单 URL 抓取超时（秒）
    link_enrich_timeout_s: float = 20.0
    # 并发抓取数。太大会被目标站限流/封 IP，也会挤压事件循环。
    link_enrich_concurrency: int = 4
    # 抓取缓存有效期（小时）。默认 7 天：岗位页一周内基本不变，
    # 而"同一个文件重复导入"是最常见的操作，缓存能直接省掉整轮出网。
    link_enrich_cache_ttl_hours: int = 168
    # 单个响应的字节上限（2MB）。超过即截断并标记，避免超大页面吃光内存。
    link_enrich_max_bytes: int = 2_000_000
    # 从链接正文里最多取多少字符当 description（也是 B3-2 喂给模型的正文上限，
    # 主计划 §4.1 L3 定的就是 ≤4k 字符）
    link_enrich_max_text_chars: int = 4000
    # 重定向最大跳数。**每一跳都会重新过 SSRF 守卫**，见 `link_enrich/fetch.py`。
    link_enrich_max_redirects: int = 5

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
