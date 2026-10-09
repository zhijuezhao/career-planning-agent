from functools import lru_cache

from pydantic import model_validator
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

    # 部署变量（由 docker-compose / 运维注入，应用自身不消费；声明出来是为了
    # 让 `.env` 能通过 pydantic-settings 的 extra="forbid" 校验 —— 否则整份
    # `.env` 会直接 ValidationError、后端启动失败）
    postgres_db: str = "career_planning"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    redis_password: str = ""

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

    # Embedding - 阿里云百炼（DASHSCOPE_*：与 EMBEDDING_* 二选一，走同一 provider 配置）
    dashscope_api_key: str = ""
    qwen_embedding_model: str = ""

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

    # ── B3 切片（2026-10-03 用户拍板）────────────────────────────────────────────
    # 实测用户 524 行表每行约 6.3 秒（3 次 LLM）→ 整表一次要 ~55 分钟，
    # 一个后台任务跑不完，进程重启就丢进度；而且旧实现还会被 `import_max_rows` 截断。
    # 所以按行切成有序小片，逐片处理、**片间暂停等人工确认**（`awaiting_confirmation`）：
    # 既保证"不丢行"（清单 + 三层完整性校验），又让单批耗时/花费可控、可中断可续。
    #
    # 为什么默认 50：50 行 ≈ 5 分钟/片，失败重跑代价小；524 行 → 11 片。
    # env `IMPORT_SLICE_SIZE` 可覆盖。
    import_slice_size: int = 50

    # ── B4-c 聚合阶段（2026-10-03）────────────────────────────────────────────────
    # 最后一片落完之后，从 `job_raw_data` 读全量 → 按 `(岗位名, 等级)` 分组 →
    # 每组 1 次「综合画像卡」+ 1 次六维评分 → 写 `job_profiles`。
    # 单独一个开关是因为它是**唯一**一步"导入完还要再烧一批 LLM"的动作
    # （本表约 87 组 ≈ 174 次调用），出问题时可以关掉、先保原始数据。
    # 关闭后仍可用 `scripts/rerun_aggregate.py` 事后补跑。
    import_aggregate_enabled: bool = True

    # ── B5 技能维度（2026-10-03 用户拍板「A+B」）──────────────────────────────────
    # A：把 `key_skills` 拼进**岗位向量**（`job_matcher.build_job_text`）→ 负责召回；
    # B：单独算「学生技能 ∩ 岗位核心技能」命中率 → 负责可解释。
    # 这里是 B 的权重：与向量/六维**混合**（`base*(1-w) + hit_ratio*w`），
    # 而不是加第三项再归一化 —— 后者会改变既有的 0.4/0.6 比例、让历史分数不可比。
    # 设 0 = 只把命中情况写进 analysis、不计入总分（`w=0` 时与改动前逐字一致）。
    matching_skill_weight: float = 0.15

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
    # ── B3-2：L3（LLM 精简提取）的**独立开关**，默认 off ──
    # 为什么与 `link_enrich_enabled` 分开（2026-09-27 用户裁决 A）：零成本层（L0/L1/L2）
    # 与 LLM 层（L3）的风险完全不同 —— 前者只花流量、后者花 token。分开之后可以先只开
    # 零成本层跑一段时间，确认抓取质量与目标站限流情况，再单开这一层。
    link_enrich_llm_enabled: bool = False
    # LLM 预算（§4.5）。**0 或负数 = 不限制**；要彻底关掉 LLM 层请用上面的开关。
    # 花费规模由"这张表里有多少个不同域名"决定，那是上传者决定的，所以必须有闸门。
    # 超限只停止后续调用并标 `budget_exceeded`，**保留**已得到的规则结果。
    link_enrich_max_llm_calls: int = 10
    link_enrich_max_tokens: int = 50_000

    # Web search - Tavily
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"

    # HTTP / 日志（`.env.production.example` 里已文档化，这里必须真实接线，
    # 否则"配了却不生效"；见 2026-10-09 安全审计 M-6）
    #: 允许的跨域来源（逗号分隔）；**追加**在本地开发默认来源之后，不会挤掉 dev 前端
    cors_origins: str = ""
    #: 预留：当前版本未接线 TrustedHostMiddleware，设置它不会生效
    allowed_hosts: str = ""
    #: 留空 = 开发 DEBUG / 生产 INFO（与历史行为一致）
    log_level: str = ""
    #: 文件日志基名（按天轮转：`logs/app_YYYY-MM-DD.log`）
    log_file: str = "./logs/app.log"

    @property
    def cors_origin_list(self) -> list[str]:
        """开发默认来源 + `CORS_ORIGINS` 配置（去空、去重、保序）。"""
        defaults = ["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"]
        configured = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        merged: list[str] = []
        for origin in [*defaults, *configured]:
            if origin not in merged:
                merged.append(origin)
        return merged

    @model_validator(mode="after")
    def _guard_production_jwt_secret(self) -> "Settings":
        """生产环境禁止用占位符/弱密钥启动。

        背景（2026-10-09 安全审计 P1-4）：`jwt_secret_key` 的默认值是公开的
        `change-me-...`；`.env` 一旦漏配，任何人都能用这个公开密钥伪造 admin token。
        所以生产直接**拒绝启动**（fail closed），而不是打条日志继续跑。
        """
        if self.app_env.strip().lower() not in {"production", "prod"}:
            return self

        secret = self.jwt_secret_key.strip()
        placeholder_markers = ("change", "your", "secret_key", "placeholder", "example")
        looks_placeholder = any(marker in secret.lower() for marker in placeholder_markers)
        if len(secret) < 32 or looks_placeholder:
            raise ValueError(
                "JWT_SECRET_KEY 未设置或仍是占位符/弱密钥，拒绝以 production 启动。"
                "请生成强随机值后写入 .env：openssl rand -hex 32"
            )
        return self

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
