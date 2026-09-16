from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MatchResultInput(BaseModel):
    """单个岗位匹配结果（前端回填，恰好 3 项，见接口契约）。"""
    job_profile_id: int
    match_score: float


class ReportGenerateRequest(BaseModel):
    profile_snapshot_id: int
    matching_results: list[MatchResultInput]


class ReportRecordSummary(BaseModel):
    """报告记录列表项：不含 report_text。"""
    id: int
    user_id: int
    profile_snapshot_id: int
    serial_no: UUID
    description: str
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportRecordResponse(ReportRecordSummary):
    """报告记录详情：含完整 report_text 与惰性 Word 路径。"""
    report_text: str
    word_file_path: str | None = None

    model_config = ConfigDict(from_attributes=True)