from __future__ import annotations


def build_portrait_text(five_layers: dict) -> str:
    """把学生五层画像拼成**向量文本**。

    ⚠️ B5（2026-10-03）：技能必须先过 `core.skills.normalise_skills()`。
    岗位侧向量文本用的是同一套归一化（`job_matcher.build_job_text`），
    两边不一致的话 `Java开发`（学生写的）与 `Java`（岗位写的）在向量空间里
    就是两个词，"技能匹配"会被系统性低估。
    """
    from app.core.skills import normalise_skills

    parts: list[str] = []

    intention = five_layers.get("intention", {})
    positions = intention.get("target_position", [])
    industries = intention.get("target_industry", [])
    cities = intention.get("target_city", [])
    if positions:
        parts.append(f"目标岗位：{'、'.join(positions)}")
    if industries:
        parts.append(f"目标行业：{'、'.join(industries)}")
    if cities:
        parts.append(f"目标城市：{'、'.join(cities)}")

    hard_skills = five_layers.get("hard_skills", {})
    tags = normalise_skills(hard_skills.get("tags", []))
    edu = hard_skills.get("education", {})
    certs = hard_skills.get("certificates", [])
    if tags:
        parts.append(f"技术栈：{'、'.join(tags)}")
    if edu.get("school"):
        parts.append(f"学历：{edu['school']} {edu.get('degree', '')} {edu.get('major', '')}")
    if certs:
        parts.append(f"证书：{'、'.join(certs)}")

    soft_skills = five_layers.get("soft_skills", {})
    soft_tags = soft_skills.get("tags", [])
    if soft_tags:
        parts.append(f"软技能：{'、'.join(soft_tags)}")

    practice = five_layers.get("practice", {})
    work = practice.get("work_experiences", [])
    projects = practice.get("projects", [])
    if work:
        descs = [f"{w.get('company', '')}-{w.get('position', '')}" for w in work[:3]]
        parts.append(f"工作经历：{'；'.join(descs)}")
    if projects:
        names = [p.get("name", "") for p in projects[:3]]
        parts.append(f"项目经历：{'、'.join(names)}")

    traits = five_layers.get("traits", {})
    strengths = traits.get("strengths", [])
    if strengths:
        parts.append(f"优势：{'、'.join(strengths)}")

    return "\n".join(parts)
