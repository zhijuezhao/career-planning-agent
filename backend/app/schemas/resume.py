from datetime import datetime

from pydantic import BaseModel


class ResumeStatusResponse(BaseModel):
    resume_id: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeDetailResponse(BaseModel):
    resume_id: int
    file_name: str
    status: str
    page_count: int | None = None
    parsed_data: dict
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeUploadResponse(BaseModel):
    resume_id: int
    status: str  # "parsed"
    five_layers: dict | None = None
    dimension_scoring: dict | None = None

    model_config = {"from_attributes": True}
