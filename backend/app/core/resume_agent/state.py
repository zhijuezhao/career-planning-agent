from __future__ import annotations

from typing import TypedDict


class ResumeState(TypedDict, total=False):
    resume_id: int
    user_id: int
    file_path: str

    raw_text: str
    page_count: int
    truncated: bool

    parsed_resume: dict
    five_layers: dict
    dimension_scoring: dict | None
    basic_info: dict

    profile_id: int
    embedding_content: str
    embedding: list[float] | None

    report_text: str

    status: str
    error_message: str | None
