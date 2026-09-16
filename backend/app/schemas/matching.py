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
    max_distance: float = 0.5


class MatchRunResponse(BaseModel):
    user_id: int
    profile_snapshot_id: int
    total: int
    results: list[MatchResultItem]