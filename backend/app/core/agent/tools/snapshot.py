"""用户画像只读工具（P4 / C2）：`user_snapshot` —— **0 LLM 调用**。

给 agent 补上「这名学生自己是谁」的事实：简历回填表单 + 最近一次快照（六维分数、五层画像）。
没有它，模型只能空谈职业建议；有它，才能说"你的技术维度 4/5，而这个岗位要求 5"。

数据口径（**与匹配链路一致**）
------------------------------
候选方六维分数读的是**快照里冻结的 JSON**（`profile_snapshots.six_dim_scores_json`），
不是 `dimension_scores` 表 —— `job_matcher` 就是这么读的（见其 `_candidate_scores` 注释：
"读快照冻结 JSON，不再查 DimensionScore candidate 行"）。工具跟它保持一致，
否则会出现"聊天里说的分数"与"匹配用的分数"对不上。

🔒 隐私：`user_id` 由 Agent 运行时**注入且强制覆盖**（见 `core/agent/nodes.py`
`_inject_runtime_args`）—— 模型即便自己填一个 id 也会被顶掉，所以学生**无法**用这个工具
读别人的画像。这是 P4 顺手补上的硬化（此前 `user_id` 只在"模型没给"时才注入）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import func, select

from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.student_profile import StudentProfile
from app.infrastructure.database import async_session_factory

#: 简历表单里回给模型的键上限（表单可能有几百个字段，全塞进去只是白烧上下文）
_MAX_FORM_KEYS = 40


def _form_summary(form: Any) -> dict[str, Any]:
    """简历表单摘要：**值的形状**（标量直接给，复杂结构只给键名列表）。

    这样模型知道"填了什么"，又不会被一整棵嵌套树撑爆上下文。
    """
    if not isinstance(form, dict):
        return {}
    summary: dict[str, Any] = {}
    for key, value in list(form.items())[:_MAX_FORM_KEYS]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[str(key)] = value
        elif isinstance(value, list):
            summary[str(key)] = {"type": "list", "count": len(value)}
        elif isinstance(value, dict):
            summary[str(key)] = {"type": "object", "keys": list(value.keys())[:10]}
        else:
            summary[str(key)] = {"type": type(value).__name__}
    return summary


@tool
async def user_snapshot(user_id: int) -> dict:
    """Read the **current user's own** profile: resume form + latest ability snapshot.

    Use this whenever the answer depends on **this student's own** background —
    e.g. "我适合什么岗位"、"我的能力差距在哪"、"我的分数怎么样". It returns the frozen
    six-dimension scores of the latest snapshot (the same numbers the matching engine uses).

    Args:
        user_id: 由系统自动注入（模型**无需也无需尝试**提供；给了也会被覆盖）。

    Returns:
        Dict: `{"has_profile": bool, "has_snapshot": bool, "resume_form": {...},
        "latest_snapshot": {...}}`。没有画像/快照时 `has_*` 为 False 并附 `note`，
        以便如实告诉用户"还没建立画像"，而不是编一个。
    """
    async with async_session_factory() as session:
        profile = await session.get(StudentProfile, user_id)
        snapshot_count = (
            await session.execute(
                select(func.count())
                .select_from(ProfileSnapshot)
                .where(ProfileSnapshot.user_id == user_id)
            )
        ).scalar() or 0
        latest = (
            await session.execute(
                select(ProfileSnapshot)
                .where(ProfileSnapshot.user_id == user_id)
                # 同秒创建时用 id 兜底，保证"最新"是确定的
                .order_by(ProfileSnapshot.created_at.desc(), ProfileSnapshot.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    payload: dict[str, Any] = {
        "has_profile": profile is not None,
        "has_snapshot": latest is not None,
        "snapshot_count": snapshot_count,
    }

    if profile is not None:
        payload["resume_form"] = _form_summary(profile.resume_form)
        payload["profile_updated_at"] = (
            profile.updated_at.isoformat() if profile.updated_at else None
        )

    if latest is not None:
        payload["latest_snapshot"] = {
            "serial_no": str(latest.serial_no),
            "description": latest.description,
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
            "matched_at": latest.matched_at.isoformat() if latest.matched_at else None,
            # 六维分数：与匹配链路同源（快照冻结 JSON），形状容错在 matching 层已有先例
            "six_dim_scores": latest.six_dim_scores_json,
            "five_layers": latest.five_layers_json,
        }

    if profile is None and latest is None:
        payload["note"] = "该用户还没有建立能力画像（无简历表单、也无快照），请先引导其完成画像"
    elif latest is None:
        payload["note"] = "该用户有简历表单但还没有能力快照（未做画像分析）"

    logger.info(
        "user_snapshot | user_id={} | has_profile={} | has_snapshot={} | snapshots={}",
        user_id,
        payload["has_profile"],
        payload["has_snapshot"],
        snapshot_count,
    )
    return payload


__all__ = ["user_snapshot"]
