"""岗位信息的字段分组 —— **岗位信息 vs 岗位画像必须分开**。

用户 2026-09-27 明确要求（原话）::

    我的岗位信息和岗位画像一定要区分开，岗位信息是岗位的信息，后期我对这些岗位信息
    我有二次开发需求。画像是用来做人岗匹配，这些画像是精提出来的，是每个岗位综合的画像。

本模块把两组的**唯一真相**写在一处，任何写入方都必须按组行事：

- ``JOB_INFO_FIELDS`` —— **岗位信息**（事实）。来自导入表，或对源文本的**确定性解析**
  （见 ``career_fields.py``）。用户会在此基础上做二次开发 →
  **任何模型派生流程都不许覆盖它**。
- ``PORTRAIT_FIELDS`` —— **岗位画像**（模型精提出的综合画像），服务于**人岗匹配**。
  只有画像写入器（``job_persist_service.apply_job_portrait``）能碰。

为什么需要这个模块（历史教训，2026-09-27 实测）
------------------------------------------------
``portrait_builder`` 的输出键里混了两类东西：

- ``five_dimensions`` / ``outlook`` / ``summary`` → 确实是**画像**；
- ``career_paths`` / ``transition_roles`` → 其实是**岗位信息**（源表里的
  「岗位晋升」「换岗方向」两列），却被 portrait 一起写进了
  ``career_path`` / ``transition_paths``。

而 ``upsert_job_profile`` 走同一个 upsert、同一批列 → **重跑画像会把用户自己的
岗位信息覆盖掉**。加上 portrait 还会静默失败返回默认值，等于"用户的数据被一个
跑挂了的模型悄悄改掉"。现在：岗位信息**只由确定性解析填充**，画像**只写画像列**。

``summary`` 的归类说明
----------------------
它由 portrait 产出、是"综合摘要"，所以归入 ``PORTRAIT_FIELDS``。
它也是三个画像字段里唯一"看起来像岗位信息"的 —— 如果用户认为它属于岗位信息，
把它挪到 ``JOB_INFO_FIELDS`` 即可（改动只在这一个文件）。
"""

from __future__ import annotations

from typing import Any

#: **岗位信息**（事实）：源数据 + 对源文本的确定性解析。模型派生流程不得覆盖。
#:
#: ⚠️ 这里**没有** `company_id`：它不是岗位自身的属性，而是"谁在招谁"（多对多，2026-09-27
#: 任务 3 已把该列从 `job_profiles` 删掉，公司归属的唯一真相是 `job_company_links`）。
#: 本集合会被 `rerun_portrait.py` / 测试当作 `getattr(profile, column)` 的列清单遍历，
#: 所以**只能放真实存在的列**（放一个已删除的列 = 直接 AttributeError）。
JOB_INFO_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "industry",
        "level",
        "salary_range",
        "education_requirement",
        "experience_requirement",
        "hard_skills",
        "soft_skills",
        "career_path",
        "transition_paths",
        "certificates",
    }
)

#: **岗位画像**（模型精提，用于人岗匹配）：只有画像写入器可以写。
PORTRAIT_FIELDS: frozenset[str] = frozenset(
    {
        "requirement_intensity",
        "outlook",
        "summary",
    }
)

#: 导入流水线/画像工具用的**中间键** → 目标列名（仅用于跨模块传参，不是 DB 列）
PIPELINE_KEY_TO_COLUMN: dict[str, str] = {
    # 2026-09-27 P5：画像的维度块由**英文五维**改为**中文六维**，键名随之改名；
    # 旧键 `five_dimensions` 保留映射（老生产者/老模型输出仍能收下，不至于静默丢画像）
    "six_dimensions": "requirement_intensity",
    "five_dimensions": "requirement_intensity",
    "career_paths": "career_path",
    "transition_roles": "transition_paths",
    "salary": "salary_range",
}

# 两组必须互不相交 —— 不变量在导入期就该炸掉，而不是等到线上把用户数据写坏
if JOB_INFO_FIELDS & PORTRAIT_FIELDS:  # pragma: no cover - 定义错才会命中
    raise RuntimeError(
        f"字段分组重叠：{sorted(JOB_INFO_FIELDS & PORTRAIT_FIELDS)}"
        "（岗位信息与岗位画像必须互斥）"
    )


def portrait_payload(data: dict[str, Any]) -> dict[str, Any]:
    """从流水线行里**只取画像字段**（列名口径），用于画像写入器。

    兼容流水线的中间键（``five_dimensions`` → ``requirement_intensity``）。
    空值（``None`` / ``""`` / ``[]`` / ``{}``）不进结果 —— `空值不算"本次提供了"`。
    """
    payload: dict[str, Any] = {}
    for key, value in data.items():
        column = PIPELINE_KEY_TO_COLUMN.get(key, key)
        if column not in PORTRAIT_FIELDS:
            continue
        if value in (None, "", [], {}):
            continue
        payload[column] = value
    return payload


def facts_payload(data: dict[str, Any]) -> dict[str, Any]:
    """从流水线行里**只取岗位信息字段**（列名口径）。

    注意 ``career_path`` / ``transition_paths`` / ``certificates`` **不在这里**
    —— 它们由 ``career_fields.py`` 对源文本做确定性解析后填入，不取自模型产物。
    """
    payload: dict[str, Any] = {}
    for key, value in data.items():
        column = PIPELINE_KEY_TO_COLUMN.get(key, key)
        if column not in JOB_INFO_FIELDS:
            continue
        if value in (None, "", [], {}):
            continue
        payload[column] = value
    return payload


__all__ = [
    "JOB_INFO_FIELDS",
    "PIPELINE_KEY_TO_COLUMN",
    "PORTRAIT_FIELDS",
    "facts_payload",
    "portrait_payload",
]
