from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable

logger = logging.getLogger(__name__)

# 进程内任务表（单实例开发够用；多 worker 需 DB 任务表——本计划设计决策，见 brief 约束 13）
_TASKS: dict[str, dict[str, Any]] = {}


def start_snapshot_task(snapshot_factory) -> str:
    """登记一个快照任务并返回 task_id；snapshot_factory 须为 async callable。

    以 uuid4().hex 作为 task_id；工厂任务失败时在任务表中记录 failed。
    """
    task_id = uuid.uuid4().hex
    _TASKS[task_id] = {"status": "running", "message": None, "snapshot_id": None}
    try:
        factory_result = snapshot_factory(task_id)
        asyncio.ensure_future(_run(task_id, factory_result))
    except Exception as exc:  # 同步注册阶段抛错，直接在表中标记 failed
        logger.exception("snapshot task %s registration failed", task_id)
        _TASKS[task_id] = {"status": "failed", "message": str(exc), "snapshot_id": None}
    return task_id


async def _run(task_id: str, coro: Awaitable[Any]) -> None:
    try:
        snap = await coro
        _TASKS[task_id] = {"status": "done", "message": None, "snapshot_id": snap.id}
    except Exception as exc:
        logger.exception("snapshot task %s failed", task_id)
        _TASKS[task_id] = {"status": "failed", "message": str(exc), "snapshot_id": None}


def get_task(task_id: str) -> dict[str, Any] | None:
    """查询任务状态；未登记的 task_id 返回 None，由端点转 404。"""
    return _TASKS.get(task_id)
