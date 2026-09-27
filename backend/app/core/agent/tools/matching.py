"""六维对比工具（P5 / C3）：`gap_analysis` / `job_compare` —— **0 LLM 调用**，会产雷达图。

与 P4 只读工具的关系
--------------------
P4 的 `job_search` / `job_detail` / `user_snapshot` 只回**数据**（模型自己组织答案）；
本模块的两个工具更进一步：它们**直接产 `viz`**（多序列雷达），因为对这种问题
"图就是答案"（六维对比用文字描述远不如一张雷达）。

工具产出的图怎么到前端（P5 打通的链路）
----------------------------------------
工具返回 `{"...业务数据...": ..., "viz": [radar_viz]}` →
`core/agent/nodes.execute_tools` 把 `viz` **摘出来**（不进 `ToolMessage`，否则纯烧 token）
放进 `config["configurable"]["viz_sink"]` → `api/v1/chat.py` 跑完 agent 后
与 L1 工作流**同一套** SSE 下发 + `chat_messages.viz` 落库。

口径
----
两侧六维**同名**（`core/dimensions/rubrics.py::DIMENSION_ORDER`）：
- **学生侧**读快照冻结 JSON（`six_dim_scores_json`）；
- **岗位侧**读画像（`job_query_service.extract_job_dimensions`）。
**缺维一律传 `None`**（雷达断开），绝不用 0 顶替 —— 0 会被读成"这一维极差"，
而事实是"没有可比数据"。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.core.chat.viz import echarts_viz, radar_option
from app.core.dimensions.rubrics import DIMENSION_ORDER
from app.domain.models.job import JobProfile
from app.domain.services.job_query_service import (
    extract_job_dimensions,
    search_jobs,
)
from app.domain.services.snapshot_service import get_latest_snapshot
from app.infrastructure.database import async_session_factory

#: 最多一次对比几个岗位（雷达序列太多就看不清了）
MAX_COMPARE_JOBS = 5


def _candidate_dims(snapshot: Any) -> dict[str, float]:
    """学生侧六维：读**快照冻结 JSON**（与 `job_matcher._candidate_scores` 同源）。"""
    raw = getattr(snapshot, "six_dim_scores_json", None) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for dim in DIMENSION_ORDER:
        value = raw.get(dim)
        if value is None:
            continue
        try:
            out[dim] = float(value)
        except (TypeError, ValueError):
            continue
    return out


async def _resolve_job(session: Any, job_id: int | None, title: str | None) -> JobProfile | None:
    """按 id（优先）或标题定位岗位；标题走与落库唯一键同一套归一化匹配。"""
    if job_id is not None:
        job = await session.get(JobProfile, job_id)
        if job is not None:
            return job
    if title:
        jobs, _ = await search_jobs(session, keyword=title, limit=1)
        return jobs[0] if jobs else None
    return None


def _gaps(my: float | None, job: float | None) -> float | None:
    """单维差距 = **岗位要求 − 我的水平**（正数=我还差多少；负数=我超出要求）。

    任一侧缺数据 → `None`（不是 0）：没有可比数据时给 0 会谎称"刚好达标"。
    """
    if my is None or job is None:
        return None
    return round(job - my, 2)


@tool
async def gap_analysis(
    job_id: int | None = None,
    title: str | None = None,
    user_id: int = 0,
) -> dict:
    """Compare the **current user's own** six-dimension profile against **one job's**
    six-dimension requirement, and draw a radar chart.

    Use this for questions like "我和这个岗位差在哪"、"我能不能达到 XX 岗位的要求".
    For comparing several jobs' requirement levels with each other, use `job_compare`.

    Args:
        job_id: 岗位 id（优先，精确）。
        title: 岗位名（忽略大小写与空格；用于模型从自然语言里抽出来的名字）。
        user_id: 由系统自动注入（模型无需提供）。

    Returns:
        Dict: `{"found": bool, "comparable": bool, "job": {...}, "my_snapshot": {...},
        "dimensions": [...], "my_scores": {...}, "job_scores": {...}, "gaps": {...}}`，
        `comparable=True` 时**额外带 `viz`**（两序列雷达：我的能力 / 岗位要求）。
        任一侧没有六维数据时 `comparable=False` 并附 `reason`，**不出图**（不编数据）。
    """
    async with async_session_factory() as session:
        job = await _resolve_job(session, job_id, title)
        if job is None:
            logger.info("gap_analysis | 岗位未找到 | job_id={} title={!r}", job_id, title)
            return {
                "found": False,
                "comparable": False,
                "reason": f"没有找到岗位（job_id={job_id!r}, title={title!r}）",
            }

        job_scores = extract_job_dimensions(job.requirement_intensity)
        snapshot = await get_latest_snapshot(session, user_id) if user_id else None
        my_scores = _candidate_dims(snapshot) if snapshot is not None else {}
        job_payload = {
            "id": int(job.id),
            "title": job.title,
            "industry": job.industry,
            "level": job.level,
        }

    gaps = {dim: _gaps(my_scores.get(dim), job_scores.get(dim)) for dim in DIMENSION_ORDER}
    matched = [dim for dim in DIMENSION_ORDER if gaps[dim] is not None]

    result: dict[str, Any] = {
        "found": True,
        "job": job_payload,
        "my_snapshot": (
            {
                "serial_no": str(snapshot.serial_no),
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            }
            if snapshot is not None
            else None
        ),
        "dimensions": list(DIMENSION_ORDER),
        "my_scores": my_scores,
        "job_scores": job_scores,
        "gaps": gaps,
        "matched_dimensions": matched,
    }

    if not my_scores or not job_scores:
        missing = []
        if not my_scores:
            missing.append("你还没有能力画像（快照里没有六维分数）")
        if not job_scores:
            missing.append("这个岗位还没有六维画像（画像缺失或仍是旧口径）")
        result["comparable"] = False
        result["reason"] = "；".join(missing) + " → 暂不可比，先不出图（不编数据）"
        logger.info(
            "gap_analysis | 不可比 | job_id={} | has_mine={} has_job={}",
            job_payload["id"],
            bool(my_scores),
            bool(job_scores),
        )
        return result

    result["comparable"] = True
    result["viz"] = [
        echarts_viz(
            "radar",
            f"六维对比：我 vs {job_payload['title']}",
            radar_option(
                list(DIMENSION_ORDER),
                {
                    "我的能力": [my_scores.get(dim) for dim in DIMENSION_ORDER],
                    "岗位要求": [job_scores.get(dim) for dim in DIMENSION_ORDER],
                },
            ),
        )
    ]
    logger.info(
        "gap_analysis | job_id={} | matched_dims={} | gaps={}",
        job_payload["id"],
        len(matched),
        {dim: gaps[dim] for dim in matched},
    )
    return result


@tool
async def job_compare(
    titles: list[str] | None = None,
    job_ids: list[int] | None = None,
) -> dict:
    """Compare **several jobs'** six-dimension requirement levels side by side (radar chart).

    Use this when the user asks how two or more jobs differ in what they demand
    (e.g. "Java 工程师和数据分析师要求差在哪"). For comparing **the user** against
    one job, use `gap_analysis` instead.

    Args:
        titles: 岗位名列表（忽略大小写与空格），最多 5 个。
        job_ids: 岗位 id 列表（优先），最多 5 个。

    Returns:
        Dict: `{"found": bool, "jobs": [...], "dimensions": [...], "scores": {...}}`，
        至少两个岗位有六维画像时**额外带 `viz`**（每个岗位一条序列的雷达）。
    """
    wanted = list(job_ids or []) or list(titles or [])
    if not wanted:
        return {"found": False, "reason": "需要 titles 或 job_ids（至少两个岗位）"}
    wanted = wanted[:MAX_COMPARE_JOBS]

    jobs: list[dict[str, Any]] = []
    async with async_session_factory() as session:
        for item in wanted:
            job = (
                await _resolve_job(session, int(item), None)
                if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
                else await _resolve_job(session, None, str(item))
            )
            if job is None:
                jobs.append({"query": item, "found": False})
                continue
            jobs.append(
                {
                    "query": item,
                    "found": True,
                    "id": int(job.id),
                    "title": job.title,
                    "scores": extract_job_dimensions(job.requirement_intensity),
                }
            )

    found = [job for job in jobs if job.get("found")]
    comparable = [job for job in found if job["scores"]]

    result: dict[str, Any] = {
        "found": bool(found),
        "jobs": jobs,
        "dimensions": list(DIMENSION_ORDER),
        "comparable_jobs": [job["title"] for job in comparable],
    }
    if len(comparable) < 2:
        result["reason"] = "有六维画像的岗位不足 2 个 → 暂不可比，先不出图（不编数据）"
        logger.info("job_compare | 不可比 | found={} comparable={}", len(found), len(comparable))
        return result

    result["viz"] = [
        echarts_viz(
            "radar",
            "岗位六维要求对比",
            radar_option(
                list(DIMENSION_ORDER),
                {
                    job["title"]: [job["scores"].get(dim) for dim in DIMENSION_ORDER]
                    for job in comparable
                },
            ),
        )
    ]
    logger.info("job_compare | comparable={} | titles={}", len(comparable), [j["title"] for j in comparable])
    return result


__all__ = ["gap_analysis", "job_compare"]
