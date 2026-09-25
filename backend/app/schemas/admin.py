from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ── User Admin Schemas ──────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str | None
    phone: str | None
    role: str
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminUserUpdate(BaseModel):
    email: str | None = None
    phone: str | None = Field(None, max_length=20)
    role: str | None = Field(None, pattern=r"^(student|admin)$")
    status: int | None = Field(None, ge=0, le=1)
    password: str | None = Field(None, min_length=6, max_length=128)


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
    career_path: dict | None
    transition_paths: dict | None
    requirement_intensity: dict | None
    outlook: dict | None
    summary: str | None
    source_data_ids: dict | None
    # B2-2：公司实体（company_name 由接口 join 填充，ORM 上不存在该列）
    company_id: int | None = None
    company_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobProfileCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    level: str | None = Field(None, max_length=20)
    hard_skills: dict | list | None = None
    soft_skills: dict | list | None = None
    salary_range: str | None = Field(None, max_length=50)
    education_requirement: str | None = Field(None, max_length=50)
    experience_requirement: str | None = Field(None, max_length=100)
    career_path: dict | None = None
    transition_paths: dict | None = None
    requirement_intensity: dict | None = None
    outlook: dict | None = None
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
    career_path: dict | None = None
    transition_paths: dict | None = None
    requirement_intensity: dict | None = None
    outlook: dict | None = None
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
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    total: int
    items: list[ChatMessageResponse]


# ── System Config Admin Schemas ─────────────────────────────────────────────

class AIConfigResponse(BaseModel):
    id: int
    function_key: str
    provider: str
    model_name: str
    base_url: str | None
    temperature: float
    max_tokens: int
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIConfigCreate(BaseModel):
    function_key: str = Field(..., min_length=1, max_length=50)
    provider: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=100)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, ge=1, le=100000)


class AIConfigUpdate(BaseModel):
    provider: str | None = Field(None, max_length=50)
    model_name: str | None = Field(None, max_length=100)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=100000)
    is_active: bool | None = None


class AIConfigListResponse(BaseModel):
    total: int
    items: list[AIConfigResponse]


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
