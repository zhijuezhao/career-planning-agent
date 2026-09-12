from datetime import datetime

from pydantic import BaseModel, Field


class ReportGenerateRequest(BaseModel):
    profile_id: int = Field(..., description="能力画像 ID")
    target_job: str | None = Field(None, max_length=100, description="目标岗位名称")


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


class ReportDownloadResponse(BaseModel):
    report_id: int
    download_url: str
    filename: str
