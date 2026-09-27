"""维度与评分标准的公共层（学生能力侧 / 岗位能力侧共用一套维度、两套标准）。

只有 `rubrics` 一个模块，但独立成包是因为**两侧都要用它**：
- 学生侧：`core/resume_agent/`（简历解析出六维）
- 岗位侧：`core/job_agent/`（画像出六维）
放在任何一侧都会让另一侧产生反向依赖，所以放中间。
"""

from __future__ import annotations

from app.core.dimensions.rubrics import (
    DIMENSION_ORDER,
    DIMENSIONS,
    LEVEL_MEANING,
    RUBRIC_VERSION,
    RUBRICS,
    SIDE_LABELS,
    SUB_TO_TOP,
    render_rubric,
    side_label,
    validate_rubrics,
)

__all__ = [
    "DIMENSIONS",
    "DIMENSION_ORDER",
    "LEVEL_MEANING",
    "RUBRICS",
    "RUBRIC_VERSION",
    "SIDE_LABELS",
    "SUB_TO_TOP",
    "render_rubric",
    "side_label",
    "validate_rubrics",
]
