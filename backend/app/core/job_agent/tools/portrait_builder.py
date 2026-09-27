from __future__ import annotations

import json
import re

from langchain_core.tools import tool
from loguru import logger

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.job_portrait import build_portrait_messages

#: 失败重试次数（含首次）。
#: 历史教训（§20.1）：`#853` 导入时 `job_portrait` 未绑定 → 回落 `default` → 当时绑的是
#: longcat（≈25s/次），而 `LLM_REQUEST_TIMEOUT=60`；82 行里约 73 行因此失败并**静默兜底**。
#: 一次重试 + 把失败暴露给调用方，比"更长的超时"更能兜住偶发失败。
_MAX_ATTEMPTS = 2


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_DEFAULT_PORTRAIT = {
    "five_dimensions": {
        "technical": {"score": 3, "key_skills": []},
        "experience": {"score": 3, "key_skills": []},
        "soft_skills": {"score": 3, "key_skills": []},
        "education": {"score": 3, "key_skills": []},
        "responsibility": {"score": 3, "key_skills": []},
    },
    "career_paths": [],
    "transition_roles": [],
    "outlook": {
        "outlook": "成熟",
        "trend": "",
        "risk_factors": [],
    },
    "summary": "",
}

#: 我们认的画像键
_PORTRAIT_KEYS = ("five_dimensions", "outlook", "summary", "career_paths", "transition_roles")

#: ⚠️ **键名漂移兜底**（2026-09-27 实测 deepseek 同一提示词不同行给不同名字）：
#: `five_dimension_ability` / `profile_summary` / `development_outlook` …
#: 只认一个名字的话，模型换个写法下游就取不到值、**静默落回默认画像**（全 3 分/「成熟」/空摘要）。
#: 治本是提示词里钉死模板（`prompts/job_portrait.py`），这里是第二道防线。
_KEY_ALIASES: dict[str, str] = {
    "five_dimension_ability": "five_dimensions",
    "five_dimension": "five_dimensions",
    "five_dims": "five_dimensions",
    "dimensional_scores": "five_dimensions",
    "development_outlook": "outlook",
    "career_outlook": "outlook",
    "industry_outlook": "outlook",
    "profile_summary": "summary",
    "job_summary": "summary",
    "portrait_summary": "summary",
    "promotion_path": "career_paths",
    "promotion_paths": "career_paths",
    "possible_paths": "career_paths",
    "transition_path": "transition_roles",
}


def _resolve_model_keys(data: dict) -> tuple[dict, list[str]]:
    """把模型写歪的键名归一；返回 ``(归一化后的 dict, 未知顶层键列表)``。"""
    resolved: dict = {}
    unknown: list[str] = []
    for key, value in data.items():
        target = _KEY_ALIASES.get(key, key)
        if target in _PORTRAIT_KEYS:
            resolved.setdefault(target, value)
        else:
            unknown.append(key)
    return resolved, unknown


def _is_usable_five_dimensions(value: object) -> bool:
    """五维必须是「有至少一个维度带整数 score 的字典」——否则它对匹配毫无用处。"""
    if not isinstance(value, dict):
        return False
    return any(isinstance(dim, dict) and isinstance(dim.get("score"), int) for dim in value.values())


def _normalise_outlook(value: object) -> dict:
    """`outlook` 归一成对象：模型偶尔直接给一个字符串（实测库里 4 条就是这样）。"""
    if isinstance(value, dict) and value:
        return value
    if isinstance(value, str) and value.strip():
        return {"outlook": value.strip(), "trend": "", "risk_factors": []}
    return dict(_DEFAULT_PORTRAIT["outlook"])


@tool
async def portrait_builder(job_data: str) -> dict:
    """Generate a deep job portrait from cleaned job data using LLM.

    Produces a five-dimension profile (technical, experience, soft skills,
    education, responsibility), career paths, transition directions, and
    outlook assessment.

    Args:
        job_data: JSON string of the cleaned job record.

    Returns:
        Dict with five_dimensions (dict), career_paths (list),
        transition_roles (list), outlook (dict), summary (str),
        **plus** ``portrait_ok`` (bool) and ``portrait_error`` (str | None).

    ⚠️ **失败不再静默**：失败时仍返回一份默认结构（让流水线能继续），但
    ``portrait_ok=False`` 且 ``portrait_error`` 写明原因 —— 调用方**必须**把它记进统计。
    历史教训：原先失败只留一条 warning，于是 `#853` 的 82 行里约 73 行是默认值，
    而 `data_import_jobs.stats` 写着 `failed: 0`、`errors: []`（见主计划 §20.1）。

    ⚠️ **字段归属**：本工具产出的画像字段只有 `five_dimensions` / `outlook` / `summary`
    属于「岗位画像」，会被 `job_persist_service.apply_job_portrait` 按白名单写入。
    返回里的 `career_paths` / `transition_roles` **不再写进岗位信息列** —— 那两列属于
    「岗位信息」，由 `core/job_agent/career_fields.py` 对源文本做**确定性解析**
    （用户 2026-09-27 要求岗位信息与岗位画像分开）。字段分组见 `field_groups.py`。
    """
    logger.info("Portrait builder tool | job_data_len={}", len(job_data))

    last_error: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            gateway = get_llm_gateway()
            messages = build_portrait_messages(job_data)
            # function_key：由管理端「系统配置 > 功能路由」绑定模型；未配置则回落默认模型
            response = await gateway.ainvoke(messages, function_key="job_portrait")
            raw_content = (
                response.content if isinstance(response.content, str) else str(response.content)
            )

            cleaned = _strip_json_fences(raw_content)
            data = json.loads(cleaned)
            resolved, unknown = _resolve_model_keys(data)

            five = resolved.get("five_dimensions")
            summary = resolved.get("summary")
            # 「必需键缺失」才算失败；模型**多给**的键只记 warning（不该把好画像判成失败）
            blocking: list[str] = []
            warnings: list[str] = []
            if not _is_usable_five_dimensions(five):
                blocking.append("five_dimensions 缺失或不可用")
            if not (isinstance(summary, str) and summary.strip()):
                blocking.append("summary 为空")
            if unknown:
                warnings.append(f"多出未知顶层键 {sorted(unknown)}")
            if blocking:
                logger.warning(
                    "Portrait 载荷不可用 | blocking={} | 模型给的键={}",
                    blocking,
                    sorted(data),
                )
            elif warnings:
                logger.info("Portrait 载荷有额外键（不影响使用）| warnings={}", warnings)

            return {
                "five_dimensions": (
                    five if _is_usable_five_dimensions(five) else _DEFAULT_PORTRAIT["five_dimensions"]
                ),
                "career_paths": resolved.get("career_paths") or [],
                "transition_roles": resolved.get("transition_roles") or [],
                "outlook": _normalise_outlook(resolved.get("outlook")),
                "summary": summary if isinstance(summary, str) else "",
                "portrait_ok": not blocking,
                "portrait_error": "；".join(blocking) if blocking else None,
                "portrait_warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001 - 重试后仍失败则兜底，但必须让调用方看得见
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Portrait builder 第 {}/{} 次失败 | error={}",
                attempt,
                _MAX_ATTEMPTS,
                last_error,
            )

    return {**_DEFAULT_PORTRAIT, "portrait_ok": False, "portrait_error": last_error}
