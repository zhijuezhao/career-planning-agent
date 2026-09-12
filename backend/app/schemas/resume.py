from datetime import datetime

from pydantic import BaseModel


class ResumeStatusResponse(BaseModel):
    resume_id: int
    status: str
    error_message: str | None = None
    profile_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeDetailResponse(BaseModel):
    resume_id: int
    file_name: str
    status: str
    page_count: int | None = None
    parsed_data: dict
    profile_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    report_id: int
    profile_id: int
    target_job: str | None = None
    report_content: dict | None = None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}
