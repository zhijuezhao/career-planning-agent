from typing import Literal

from pydantic import BaseModel


class JourneyStatusResponse(BaseModel):
    zone: Literal["welcome", "guide", "business"]
    guide_step: Literal["resume", "parse", "match", "career", "done"] | None = None
    snapshot_id: int | None = None
    report_id: int | None = None
    report_versions: int = 0