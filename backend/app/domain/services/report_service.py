from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.career_development import build_career_development_messages
from app.core.safety.filter import append_disclaimer
from app.domain.models.report import CareerReport
from app.infrastructure.database import async_session_factory

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "reports")


def _ensure_reports_dir():
    """确保报告输出目录存在。"""
    os.makedirs(REPORTS_DIR, exist_ok=True)


def _safe_json_loads(text: str) -> dict[str, Any]:
    """安全解析 JSON。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


async def get_user_profile_data(
    user_id: int,
    profile_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """获取用户能力画像数据。"""
    from app.domain.models.profile import AbilityProfile

    result = await session.execute(
        select(AbilityProfile).where(AbilityProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None

    return {
        "direction_tag": profile.direction_tag,
        "intention": profile.intention,
        "traits": profile.traits,
        "practice": profile.practice,
        "soft_skills": profile.soft_skills,
        "hard_skills": profile.hard_skills,
    }


async def get_dimension_scores_data(
    profile_id: int,
    session: AsyncSession,
) -> dict[str, float]:
    """获取维度评分数据。"""
    from app.domain.models.dimension_score import DimensionScore

    result = await session.execute(
        select(DimensionScore).where(
            DimensionScore.profile_type == "candidate",
            DimensionScore.profile_id == profile_id,
        )
    )
    scores = result.scalars().all()

    dimension_scores: dict[str, float] = {}
    for s in scores:
        if s.sub_dimension == s.top_dimension or not s.sub_dimension:
            dimension_scores[s.top_dimension] = s.score
        else:
            if s.top_dimension not in dimension_scores:
                dimension_scores[s.top_dimension] = []
            dimension_scores[s.top_dimension].append(s.score)

    for key, val in dimension_scores.items():
        if isinstance(val, list):
            dimension_scores[key] = sum(val) / len(val) if val else 0.0

    return dimension_scores


async def get_latest_match_results(
    user_id: int,
    session: AsyncSession,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """获取最新匹配结果。"""
    from app.domain.models.report import JobMatch

    result = await session.execute(
        select(JobMatch)
        .where(JobMatch.user_id == user_id)
        .order_by(JobMatch.match_score.desc())
        .limit(top_k)
    )
    matches = result.scalars().all()

    return [
        {
            "job_profile_id": m.job_profile_id,
            "match_score": m.match_score,
            "analysis": m.match_analysis,
        }
        for m in matches
        if m.match_score is not None
    ]


async def get_latest_career_path(
    user_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """获取最新职业路线。"""
    from app.domain.models.report import GrowthPath

    result = await session.execute(
        select(GrowthPath)
        .where(GrowthPath.user_id == user_id)
        .order_by(GrowthPath.created_at.desc())
        .limit(1)
    )
    path = result.scalar_one_or_none()
    if not path:
        return None

    return {
        "target_position": path.target_position,
        "path_type": path.path_type,
        "milestones": path.milestones,
        "learning_resources": path.learning_resources,
        "generated_plan": path.generated_plan,
    }


async def get_latest_growth_plan(
    user_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """获取最新成长计划。"""
    from app.domain.models.report import GrowthPlan

    result = await session.execute(
        select(GrowthPlan)
        .where(GrowthPlan.user_id == user_id)
        .order_by(GrowthPlan.created_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        return None

    return {
        "cycle_weeks": plan.cycle_weeks,
        "intensity": plan.intensity,
        "tasks": plan.tasks,
        "progress": plan.progress,
    }


async def generate_report_content(
    user_id: int,
    profile_id: int,
    target_job: str | None,
    session: AsyncSession,
) -> dict[str, Any]:
    """生成报告内容（调用 LLM）。"""
    profile_data = await get_user_profile_data(user_id, profile_id, session)
    if not profile_data:
        raise ValueError("用户能力画像不存在")

    dim_scores = await get_dimension_scores_data(profile_id, session)
    match_results = await get_latest_match_results(user_id, session)
    career_path = await get_latest_career_path(user_id, session)
    growth_plan = await get_latest_growth_plan(user_id, session)

    basic_info = {
        "user_id": user_id,
        "profile_id": profile_id,
        "target_job": target_job,
    }

    messages = build_career_development_messages(
        basic_info_json=json.dumps(basic_info, ensure_ascii=False, indent=2),
        five_layers_json=json.dumps(profile_data, ensure_ascii=False, indent=2),
        dimension_scores_json=json.dumps(dim_scores, ensure_ascii=False, indent=2),
        match_results_json=json.dumps(match_results, ensure_ascii=False, indent=2),
        career_path_json=json.dumps(career_path or {}, ensure_ascii=False, indent=2),
        growth_plan_json=json.dumps(growth_plan or {}, ensure_ascii=False, indent=2),
    )

    gateway = get_llm_gateway()
    response = await gateway.ainvoke(messages)
    raw = response.content if isinstance(response.content, str) else str(response.content)
    report_text = append_disclaimer(raw.strip())

    return {
        "basic_info": basic_info,
        "five_layers": profile_data,
        "dimension_scores": dim_scores,
        "match_results": match_results,
        "career_path": career_path,
        "growth_plan": growth_plan,
        "report_text": report_text,
        "generated_at": datetime.utcnow().isoformat(),
    }


def generate_word_document(
    report_content: dict[str, Any],
    output_path: str,
) -> str:
    """生成 Word 文档。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    _ensure_reports_dir()

    doc = Document()
    style = doc.styles["Normal"]
    font = style.font
    font.name = "微软雅黑"
    font.size = Pt(11)

    title = doc.add_heading("生涯发展报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    basic_info = report_content.get("basic_info", {})
    if basic_info.get("target_job"):
        doc.add_paragraph(f"目标岗位：{basic_info['target_job']}")
    doc.add_paragraph(f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph()

    report_text = report_content.get("report_text", "")
    for line in report_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.startswith("*") and line.endswith("*"):
            p = doc.add_paragraph()
            run = p.add_run(line.strip("*"))
            run.italic = True
        else:
            doc.add_paragraph(line)

    doc.save(output_path)
    logger.info("Word document generated | path={}", output_path)
    return output_path


async def create_report(
    user_id: int,
    profile_id: int,
    target_job: str | None = None,
    session=None,
) -> CareerReport:
    """创建生涯发展报告（生成内容 + Word 导出）。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _create_report_impl(user_id, profile_id, target_job, session)
        return await _create_report_impl(user_id, profile_id, target_job, session)
    except Exception as exc:
        logger.warning("Failed to create report | error={}", exc)
        raise


async def _create_report_impl(
    user_id: int,
    profile_id: int,
    target_job: str | None,
    session: AsyncSession,
) -> CareerReport:
    report_content = await generate_report_content(
        user_id, profile_id, target_job, session
    )

    _ensure_reports_dir()
    filename = f"career_report_{user_id}_{uuid4().hex[:8]}.docx"
    output_path = os.path.join(REPORTS_DIR, filename)
    generate_word_document(report_content, output_path)

    version_result = await session.execute(
        select(CareerReport.version)
        .where(CareerReport.user_id == user_id, CareerReport.profile_id == profile_id)
        .order_by(CareerReport.version.desc())
        .limit(1)
    )
    latest_version = version_result.scalar_one_or_none()
    version = (latest_version or 0) + 1

    report = CareerReport(
        user_id=user_id,
        profile_id=profile_id,
        target_job=target_job,
        report_content=report_content,
        word_file_path=output_path,
        version=version,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    logger.info("Report created | user_id={} | report_id={}", user_id, report.id)
    return report


async def get_user_reports(
    user_id: int,
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list[CareerReport]:
    """获取用户的报告列表。"""
    result = await session.execute(
        select(CareerReport)
        .where(CareerReport.user_id == user_id)
        .order_by(CareerReport.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_report_by_id(
    report_id: int,
    session: AsyncSession,
) -> CareerReport | None:
    """获取单个报告。"""
    return await session.get(CareerReport, report_id)
