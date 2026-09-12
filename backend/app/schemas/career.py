from datetime import datetime

from pydantic import BaseModel, Field


class CareerPathRequest(BaseModel):
    profile_id: int = Field(..., description="能力画像 ID")
    target_job_id: int = Field(..., description="目标岗位 ID")
    current_stage: str = Field("在校学生", description="当前职业阶段")


class MilestoneItem(BaseModel):
    stage: str
    duration_months: int
    goals: list[str]
    key_actions: list[str]


class LearningResources(BaseModel):
    courses: list[str] = []
    certificates: list[str] = []
    books: list[str] = []
    projects: list[str] = []


class CareerPathResponse(BaseModel):
    id: int
    user_id: int
    target_position: str | None
    path_type: str | None
    current_abilities: dict | None
    target_abilities: dict | None
    milestones: list | None
    generated_plan: dict | None
    learning_resources: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CareerPathListResponse(BaseModel):
    total: int
    items: list[CareerPathResponse]


class GrowthPlanRequest(BaseModel):
    growth_path_id: int = Field(..., description="职业路线 ID")
    weekly_hours: int = Field(10, ge=1, le=40, description="每周可用时间（小时）")
    cycle_weeks: int = Field(12, ge=1, le=52, description="计划周期（周数）")


class TaskItem(BaseModel):
    week: str
    title: str
    description: str
    deliverables: list[str]
    time_hours: int


class GrowthPlanResponse(BaseModel):
    id: int
    user_id: int
    growth_path_id: int
    cycle_weeks: int | None
    intensity: str | None
    tasks: list | None
    progress: dict | None
    weekly_reviews: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GrowthPlanListResponse(BaseModel):
    total: int
    items: list[GrowthPlanResponse]
