from __future__ import annotations

from pydantic import BaseModel


class MatchAnalysis(BaseModel):
    vector_similarity: float
    dimension_score: float
    dimension_matches: dict
    weights_used: dict


class MatchResultItem(BaseModel):
    job_profile_id: int
    match_score: float
    distance: float
    analysis: MatchAnalysis


class MatchRunRequest(BaseModel):
    profile_snapshot_id: int
    top_k: int = 10
    # 0.65 依据实测（R-11.6）：当前 embedding provider(dashscope text-embedding-v4) 下，
    # 用户快照与岗位向量的余弦距离集中在 0.579~0.59，原默认 0.5 会导致零命中。
    max_distance: float = 0.65


class MatchRunResponse(BaseModel):
    user_id: int
    profile_snapshot_id: int
    total: int
    results: list[MatchResultItem]
