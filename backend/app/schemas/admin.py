from datetime import datetime
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
    hard_skills: dict | None
    soft_skills: dict | None
    salary_range: str | None
    education_requirement: str | None
    experience_requirement: str | None
    career_path: dict | None
    transition_paths: dict | None
    requirement_intensity: dict | None
    outlook: dict | None
    summary: str | None
    source_data_ids: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobProfileCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=100)
    level: str | None = Field(None, max_length=20)
    hard_skills: dict | None = None
    soft_skills: dict | None = None
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
    hard_skills: dict | None = None
    soft_skills: dict | None = None
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


# ── Match Admin Schemas ─────────────────────────────────────────────────────

class MatchResultResponse(BaseModel):
    id: int
    user_id: int
    profile_id: int
    job_profile_id: int
    match_score: float | None
    match_analysis: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MatchResultListResponse(BaseModel):
    total: int
    items: list[MatchResultResponse]


class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    match_id: int
    feedback_type: str | None
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackListResponse(BaseModel):
    total: int
    items: list[FeedbackResponse]


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


# ── Career Path Admin Schemas ───────────────────────────────────────────────

class GrowthPathResponse(BaseModel):
    id: int
    user_id: int
    target_position: str | None
    path_type: str | None
    current_abilities: dict | None
    target_abilities: dict | None
    milestones: dict | None
    generated_plan: dict | None
    learning_resources: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GrowthPathListResponse(BaseModel):
    total: int
    items: list[GrowthPathResponse]


class GrowthPlanResponse(BaseModel):
    id: int
    user_id: int
    growth_path_id: int
    cycle_weeks: int | None
    intensity: str | None
    tasks: dict | None
    progress: dict | None
    weekly_reviews: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GrowthPlanListResponse(BaseModel):
    total: int
    items: list[GrowthPlanResponse]


# ── Report Admin Schemas ────────────────────────────────────────────────────

class ReportResponse(BaseModel):
    id: int
    user_id: int
    profile_id: int
    target_job: str | None
    report_content: dict | None
    word_file_path: str | None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    total: int
    items: list[ReportResponse]


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


class MatchStats(BaseModel):
    avg_score: float
    total_matches: int
    feedback_count: int


class SystemHealth(BaseModel):
    database: str
    scheduler: str
    llm_gateway: str


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
