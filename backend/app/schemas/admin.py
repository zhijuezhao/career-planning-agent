from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.roles import UserRole

# ── User Admin Schemas ──────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str | None
    phone: str | None
    # B2-4：联系方式（列由 B2-0 建好，此前 ORM/接口都没暴露 → 前端永远看不到也改不了）
    qq: str | None = None
    wechat: str | None = None
    role: str
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminUserUpdate(BaseModel):
    """管理端可改的用户字段（B2-4 改造）。

    - `role` 走 `UserRole` 白名单：非法角色 422，不再"静默写入谁都不认识的角色"；
    - `qq` / `wechat` 为 B2-4 新增，`qq` 限数字（它本来就是号码）；
    - **空串一律规范化为 `None`**：管理端把输入框清空 = 真清空（NULL），
      而不是写一个 `''` 进库（`email` 是唯一列，多个 `''` 会互相冲突）。
    """

    email: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    qq: str | None = Field(None, max_length=20, pattern=r"^\d{5,20}$")
    wechat: str | None = Field(None, max_length=50)
    role: UserRole | None = None
    status: int | None = Field(None, ge=0, le=1)
    password: str | None = Field(None, min_length=6, max_length=128)

    @field_validator("email", "phone", "qq", "wechat", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """`""` / 纯空白 → `None`（清空语义）；同时去掉首尾空白。"""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class AdminUserListResponse(BaseModel):
    total: int
    items: list[AdminUserResponse]


class AdminUserStats(BaseModel):
    user_id: int
    username: str
    resume_count: int = 0
    match_count: int = 0
    report_count: int = 0
    chat_session_count: int = 0
    # B2-4：删除用户前要如实告诉管理员"还会连带删掉哪些东西"（快照/画像由数据库 CASCADE）
    snapshot_count: int = 0
    profile_count: int = 0


# ── JobProfile Admin Schemas ────────────────────────────────────────────────

class JobProfileResponse(BaseModel):
    id: int
    title: str
    industry: str | None
    level: str | None
    # JSONB 实际允许两种形状：画像结构（dict，含 tags/education 等）或提取器直接给的技能数组
    # （list）。`job_matcher.build_job_text` 两种都支持，这里不能只收 dict，
    # 否则一条 list 形状的历史/导入数据会让整个岗位列表 500。
    hard_skills: dict | list | None
    soft_skills: dict | list | None
    salary_range: str | None
    education_requirement: str | None
    experience_requirement: str | None
    # 2026-09-26 实测（真实导入 #853 的 82 条画像）：同一列存在多种形状 ——
    # `transition_paths` 5 条是字符串数组（换岗方向）/ 3 条 object；`outlook` 4 条是
    # 字符串（"成熟"/"转型中"）/ 78 条 object；`career_path` 目前全 null 但持久化层
    # （`job_persist_service` 写的是 `career_paths` 列表）同样会产出数组。
    # 只收 dict 会让**整个岗位列表 500**（与上面 hard_skills 同一类问题，实测已复现）。
    career_path: dict | list | str | None
    transition_paths: dict | list | str | None
    # P4a：所需证书（列表）。回填前为 None。
    certificates: list | None = None
    requirement_intensity: dict | None
    outlook: dict | list | str | None
    summary: str | None
    source_data_ids: dict | None
    # 2026-09-27 任务 3：这里**不再有 `company_id`** —— 岗位是角色级的，公司归属全在
    # 「在招公司」清单（`JobProfileDetail.companies`）里；`company_name` / `company_count`
    # 由接口按 `job_company_links` 现算（ORM 上都不存在这两列）。
    company_name: str | None = None
    # B2-5：有多少家公司在招这个岗位（关联表统计）
    company_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobCompanyLinkInfo(BaseModel):
    """岗位详情里的「在招公司」条目（B2-5；2026-09-27 任务 2 起 = 关联表一条 = 一次招聘）。"""
    company_id: int
    company_name: str
    industry: str | None = None
    #: 公司规模（如 `1000-9999人`）
    scale: str | None = None
    #: 地域：优先用**这次招聘**的所在地，缺失才回落到公司属性
    region: str | None = None
    city: str | None = None
    #: 本次招聘的薪资 / 原始链接
    salary: str | None = None
    source_url: str | None = None
    hit_count: int = 1
    last_seen_at: datetime | None = None
    is_primary: bool = False


class JobProfileDetail(JobProfileResponse):
    """岗位详情：比列表多一份「在招公司」清单。"""
    companies: list[JobCompanyLinkInfo] = []


class JobProfileCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    level: str | None = Field(None, max_length=20)
    hard_skills: dict | list | None = None
    soft_skills: dict | list | None = None
    salary_range: str | None = Field(None, max_length=50)
    education_requirement: str | None = Field(None, max_length=50)
    experience_requirement: str | None = Field(None, max_length=100)
    # 与 JobProfileResponse 一致：真实画像里这三种值可能是对象/数组/字符串。
    career_path: dict | list | str | None = None
    transition_paths: dict | list | str | None = None
    certificates: list | None = None
    requirement_intensity: dict | None = None
    outlook: dict | list | str | None = None
    summary: str | None = None


class JobProfileUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    level: str | None = Field(None, max_length=20)
    hard_skills: dict | list | None = None
    soft_skills: dict | list | None = None
    salary_range: str | None = Field(None, max_length=50)
    education_requirement: str | None = Field(None, max_length=50)
    experience_requirement: str | None = Field(None, max_length=100)
    # 与 JobProfileResponse 一致：真实画像里这三种值可能是对象/数组/字符串，
    # 只收 dict 会让「编辑后保存」对真实数据 422。
    career_path: dict | list | str | None = None
    transition_paths: dict | list | str | None = None
    certificates: list | None = None
    requirement_intensity: dict | None = None
    outlook: dict | list | str | None = None
    summary: str | None = None


class JobProfileListResponse(BaseModel):
    total: int
    items: list[JobProfileResponse]


# ── JobRawData Admin Schemas ────────────────────────────────────────────────

class JobRawDataResponse(BaseModel):
    id: int
    title: str
    company: str | None
    city: str | None
    salary: str | None
    industry: str | None
    description: str | None
    requirements: str | None
    source: str | None
    is_active: bool
    expire_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobRawDataListResponse(BaseModel):
    total: int
    items: list[JobRawDataResponse]


# ── Snapshot Admin Schemas（原 MatchResult/Feedback：对应 JobMatch/UserFeedback 表已删除，D9）──

class AdminSnapshotSummary(BaseModel):
    """画像快照列表项（含匹配状态与六维分数摘要）。

    P1-4 起补 `username`（LEFT JOIN users）与 `report_count`：
    管理端要显示「谁生成的」以及删除时提示「会连带删掉几份报告」。
    """
    id: int
    user_id: int
    username: str | None = None
    profile_id: int
    serial_no: UUID
    description: str
    matched: bool
    matched_at: datetime | None
    created_at: datetime
    six_dim_scores: dict
    report_count: int = 0


class AdminSnapshotDetail(AdminSnapshotSummary):
    """画像快照详情：含五层画像与原始表单；向量只回维度数，不回 1024 个浮点。"""
    five_layers: dict
    form_raw: dict
    embedding_dim: int | None = None


class AdminSnapshotUpdate(BaseModel):
    """快照可改字段（P1-4，仅这两项）。

    ⚠️ 改 `five_layers` **不会**重算 embedding 与六维分数 —— 向量仍对应快照生成时的画像。
    `extra="forbid"`：传了别的字段（如 embedding）直接 422，避免"发了却没生效"的迷惑。
    """
    description: str | None = Field(None, max_length=255)
    five_layers: dict | None = None

    model_config = {"extra": "forbid"}


class AdminSnapshotListResponse(BaseModel):
    total: int
    items: list[AdminSnapshotSummary]


# ── Dimension Weight Admin Schemas ──────────────────────────────────────────

class DimensionWeightResponse(BaseModel):
    id: int
    job_category: str
    top_dimension: str
    weight: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DimensionWeightCreate(BaseModel):
    job_category: str = Field(..., min_length=1, max_length=50)
    top_dimension: str = Field(..., min_length=1, max_length=50)
    weight: float = Field(..., ge=0.0, le=1.0)


class DimensionWeightUpdate(BaseModel):
    weight: float = Field(..., ge=0.0, le=1.0)


class DimensionWeightListResponse(BaseModel):
    total: int
    items: list[DimensionWeightResponse]


# ── Report Admin Schemas ────────────────────────────────────────────────────

class AdminReportSummary(BaseModel):
    """报告记录列表项（基于 report_records；不含 report_text）。"""
    id: int
    user_id: int
    profile_snapshot_id: int
    serial_no: UUID
    description: str
    version: int
    created_at: datetime


class AdminReportDetail(AdminReportSummary):
    """报告记录详情：含完整 report_text 与惰性 Word 路径。"""
    report_text: str
    word_file_path: str | None = None


class AdminReportListResponse(BaseModel):
    total: int
    items: list[AdminReportSummary]


# ── Chat Admin Schemas ──────────────────────────────────────────────────────

class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: int
    title: str | None
    summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    total: int
    items: list[ChatSessionResponse]


class ChatMessageResponse(BaseModel):
    id: int
    session_id: UUID
    role: str
    content: str
    tokens_used: int
    model_used: str | None
    #: C1 可视化载荷（数组，契约见 `app/core/chat/viz.py`）；无图时为 None
    viz: list[dict] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    total: int
    items: list[ChatMessageResponse]


# ── Dashboard Stats Schemas ─────────────────────────────────────────────────

class DashboardOverview(BaseModel):
    total_users: int
    total_resumes: int
    total_job_profiles: int
    total_matches: int
    total_reports: int
    total_chat_sessions: int


class UserGrowthStat(BaseModel):
    date: str
    count: int


class JobCategoryStat(BaseModel):
    category: str
    count: int


class QualityDistribution(BaseModel):
    grade: str
    count: int


class SnapshotStats(BaseModel):
    """画像快照/匹配进度（替代原 MatchStats：匹配明细已不落表，D8）。"""
    total_snapshots: int
    matched_snapshots: int
    pending_snapshots: int


class SystemHealth(BaseModel):
    database: str
    scheduler: str
    llm_gateway: str


class ImportOverview(BaseModel):
    """导入任务总览（P1-6 仪表盘用）。

    注意语义：`total_rows/success_rows/error_rows` 是**所有任务求和**，不是单次导入。
    其中 `success_rows` 在 S7-4（真实落库）落地后会等于「实际入库条数」。
    """
    total_jobs: int
    pending: int
    processing: int
    completed: int
    failed: int
    total_rows: int
    success_rows: int
    error_rows: int
    last_import_at: datetime | None = None


# ── Import Job Admin Schemas ────────────────────────────────────────────────

class ImportJobResponse(BaseModel):
    id: int
    file_name: str
    file_size: int
    status: str
    total_rows: int
    processed_rows: int
    success_count: int
    error_count: int
    errors: list | None
    # B2-2：落库统计（persist 阶段）；B3 会加链接解析/token 统计，前端导入详情直接展示
    stats: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImportJobListResponse(BaseModel):
    total: int
    items: list[ImportJobResponse]


class ImportProgressResponse(BaseModel):
    job_id: int
    status: str
    total_rows: int
    processed_rows: int
    success_count: int
    error_count: int
    progress_pct: float


# ── LLM 配置中心 Schemas（B2-1：供应商 / 模型 / 功能路由 / 连通性）─────────────

class LLMProviderResponse(BaseModel):
    """供应商回显：**永不回明文 api_key**，只有掩码与是否已配置。"""
    id: int
    name: str
    base_url: str | None
    enabled: bool
    sort_order: int
    api_key_set: bool
    api_key_masked: str
    model_count: int = 0
    created_at: datetime
    updated_at: datetime


class LLMProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    enabled: bool = True
    sort_order: int = 0


class LLMProviderUpdate(BaseModel):
    """`api_key` 不传=不改；传空串=清除密钥（该供应商随之退出网关）。"""
    name: str | None = Field(None, min_length=1, max_length=100)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    enabled: bool | None = None
    sort_order: int | None = None


class LLMProviderListResponse(BaseModel):
    total: int
    items: list[LLMProviderResponse]


class LLMModelResponse(BaseModel):
    id: int
    provider_id: int
    provider_name: str | None = None
    model_name: str
    display_name: str | None
    kind: str
    dim: int | None
    temperature: float | None
    max_tokens: int | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class LLMModelCreate(BaseModel):
    provider_id: int
    model_name: str = Field(..., min_length=1, max_length=100)
    display_name: str | None = Field(None, max_length=100)
    kind: Literal["chat", "embedding"] = "chat"
    dim: int | None = Field(None, ge=1, le=65536)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=100000)
    enabled: bool = True


class LLMModelUpdate(BaseModel):
    model_name: str | None = Field(None, min_length=1, max_length=100)
    display_name: str | None = Field(None, max_length=100)
    kind: Literal["chat", "embedding"] | None = None
    dim: int | None = Field(None, ge=1, le=65536)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=100000)
    enabled: bool | None = None


class LLMModelListResponse(BaseModel):
    total: int
    items: list[LLMModelResponse]


class FunctionRouteResponse(BaseModel):
    """一个功能键的生效情况。`source=db` 才表示管理端配置真的生效（含各项前置校验）。"""
    function_key: str
    label: str
    kind: str
    wired: bool = True           # 调用点是否已接入（False = 绑定也不生效，B3-2 才接）
    bound_model_id: int | None = None
    bound_model: str | None = None
    source: str = "env"          # db | env
    effective: str = ""          # 实际生效的模型（或 env 回退说明）
    fallback: str = ""           # 未配置时的回退
    warning: str | None = None   # 绑定了但未生效的原因（模型/供应商禁用、kind 不符、无密钥…）
    updated_at: datetime | None = None


class FunctionRouteListResponse(BaseModel):
    total: int
    items: list[FunctionRouteResponse]


class FunctionRouteUpdate(BaseModel):
    """`model_id: null` = 解绑（回到 env/default 行为）。字段必填，避免"没传却以为改了"。"""
    model_id: int | None

    model_config = {"extra": "forbid"}


class LLMConnectivityTestResponse(BaseModel):
    ok: bool
    model: str
    kind: str
    latency_ms: int
    dim: int | None = None
    dim_expected: int | None = None
    output_preview: str | None = None
    detail: str = ""


# ── Company Admin Schemas（B2-2，需求 3：公司信息导航）───────────────────────

class CompanyResponse(BaseModel):
    id: int
    name: str
    industry: str | None
    city: str | None
    job_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanyUpdate(BaseModel):
    """人工修正公司信息（导入自动识别的值可改）。全部可选，不传=不改。"""
    name: str | None = Field(None, min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=50)


class CompanyJobSummary(BaseModel):
    """公司详情里的岗位摘要（完整字段请走岗位管理页）。"""
    id: int
    title: str
    industry: str | None = None
    level: str | None = None
    salary_range: str | None = None
    created_at: datetime


class CompanyDetail(CompanyResponse):
    jobs: list[CompanyJobSummary] = []


class CompanyListResponse(BaseModel):
    total: int
    items: list[CompanyResponse]


class CompanySyncResponse(BaseModel):
    synced: int
    with_jobs: int
    #: **遗留字段，恒为 0**（仅为兼容旧前端保留）。B2-5 曾用它报告"把历史上只有
    #: `job_profiles.company_id` 的关联补进 `job_company_links` 的行数"；2026-09-27 任务 2
    #: 起岗位不再写 `company_id`（任务 3 已删该列）→ 回填无对象，`/companies/sync` 只重算计数。
    links_created: int = 0


# ── Match Record Admin Schemas（B2-3，需求 3：匹配明细）────────────────────────

class AdminMatchRecordSummary(BaseModel):
    """匹配明细列表项：**不含 analysis**（体积大，详情接口单独取）。"""
    id: int
    profile_snapshot_id: int
    snapshot_serial_no: UUID | None = None
    user_id: int | None = None
    username: str | None = None
    job_profile_id: int
    job_title: str | None = None
    rank: int
    score: float | None
    distance: float | None
    status: str
    duration_ms: int | None
    matched_at: datetime


class AdminMatchRecordDetail(AdminMatchRecordSummary):
    """明细详情：附带完整打分分析（向量相似度 / 六维对比 / 权重）。"""
    analysis: dict | None = None
    job_industry: str | None = None


class AdminMatchRecordListResponse(BaseModel):
    total: int
    items: list[AdminMatchRecordSummary]


class AdminMatchRecordStats(BaseModel):
    """明细总览（页面头部用）：条数、成功/失败、快照数、平均分与平均耗时。"""
    total: int
    success: int
    failed: int
    snapshots: int
    avg_score: float | None = None
    avg_duration_ms: float | None = None
