from datetime import datetime

from pydantic import BaseModel, Field


class MatchRunRequest(BaseModel):
    profile_id: int = Field(..., description="能力画像 ID")
    top_k: int = Field(10, ge=1, le=50, description="返回匹配数量上限")
    max_distance: float = Field(0.5, ge=0.0, le=1.0, description="最大余弦距离阈值")


class DimensionMatchDetail(BaseModel):
    user_score: float
    job_score: float
    weight: float
    match_ratio: float


class MatchAnalysis(BaseModel):
    vector_similarity: float
    dimension_score: float
    dimension_matches: dict[str, DimensionMatchDetail]
    weights_used: dict[str, float]


class MatchResultItem(BaseModel):
    job_profile_id: int
    match_score: float
    distance: float
    analysis: MatchAnalysis


class MatchRunResponse(BaseModel):
    user_id: int
    profile_id: int
    total: int
    results: list[MatchResultItem]


class MatchListResponse(BaseModel):
    total: int
    items: list[MatchResultItem]


class FeedbackCreateRequest(BaseModel):
    match_id: int = Field(..., description="匹配结果 ID")
    feedback_type: str = Field(
        ...,
        pattern=r"^(like|dislike|applied|saved)$",
        description="反馈类型：like/dislike/applied/saved",
    )
    comment: str | None = Field(None, max_length=500, description="反馈备注")


class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    match_id: int
    feedback_type: str
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackListResponse(BaseModel):
    total: int
    items: list[FeedbackResponse]
