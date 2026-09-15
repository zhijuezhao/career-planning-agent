from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileForm(BaseModel):
    """简历表单（单一权威来源，整表覆盖）。"""
    resume_form: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    resume_form: dict[str, Any]


class ProfileResponse(BaseModel):
    """GET/PUT /profile 返回体：仅 resume_form（展开结构由前端组装）。"""
    resume_form: dict[str, Any] = Field(default_factory=dict)


class SnapshotCreateResponse(BaseModel):
    task_id: str


class SnapshotPollResponse(BaseModel):
    """快照任务轮询。
    status: "running" | "done" | "failed"
    message: 仅 failed 时有
    snapshot_id: 仅 done 时有
    """
    status: str
    message: str | None = None
    snapshot_id: int | None = None


class SnapshotSummary(BaseModel):
    """快照列表项：id/serial_no/description/created_at，不含大 JSON。"""
    id: int
    serial_no: UUID
    description: str
    created_at: datetime


class SnapshotDetailResponse(BaseModel):
    """快照详情：冻结的 form/five_layers/dimension_scores + has_embedding。

    永不返回 embedding 向量本身。
    """
    id: int
    serial_no: UUID
    description: str
    created_at: datetime
    form: dict[str, Any] = Field(default_factory=dict)
    five_layers: dict[str, Any] = Field(default_factory=dict)
    dimension_scores: dict[str, Any] = Field(default_factory=dict)
    has_embedding: bool