from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.dimensions.rubrics import DIMENSION_ORDER, DIMENSIONS


class BasicInfo(BaseModel):
    name: str | None = None
    gender: str | None = None
    age: int | None = None
    phone: str | None = None
    email: str | None = None
    school: str | None = None
    degree: str | None = None
    major: str | None = None
    graduation_year: int | None = None


class ExpectedSalary(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str = "CNY"
    raw: str | None = None


class Intention(BaseModel):
    target_industry: list[str] = Field(default_factory=list)
    target_position: list[str] = Field(default_factory=list)
    target_city: list[str] = Field(default_factory=list)
    expected_salary: ExpectedSalary = Field(default_factory=ExpectedSalary)
    employment_type: str | None = None
    job_level: str | None = None


class Traits(BaseModel):
    personality_tags: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    self_evaluation: str | None = None
    evidence: list[str] = Field(default_factory=list)


class CampusExperience(BaseModel):
    org: str = ""
    role: str = ""
    period: str = ""
    description: str = ""
    skills_used: list[str] = Field(default_factory=list)
    is_leadership: bool = False


class WorkExperience(BaseModel):
    company: str = ""
    position: str = ""
    period: str = ""
    description: str = ""
    achievements: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str = ""
    role: str = ""
    period: str = ""
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    is_original: bool = False


class Competition(BaseModel):
    name: str = ""
    award: str = ""
    period: str = ""


class Practice(BaseModel):
    campus_experiences: list[CampusExperience] = Field(default_factory=list)
    work_experiences: list[WorkExperience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    competitions: list[Competition] = Field(default_factory=list)


class SoftSkills(BaseModel):
    tags: list[str] = Field(default_factory=list)
    scored: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    major: str | None = None
    gpa: str | None = None
    rank: str | None = None
    period: str | None = None


class HardSkills(BaseModel):
    tags: list[str] = Field(default_factory=list)
    scored: dict[str, float] = Field(default_factory=dict)
    education: Education = Field(default_factory=Education)
    certificates: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class ParsedResume(BaseModel):
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    intention: Intention = Field(default_factory=Intention)
    traits: Traits = Field(default_factory=Traits)
    practice: Practice = Field(default_factory=Practice)
    soft_skills: SoftSkills = Field(default_factory=SoftSkills)
    hard_skills: HardSkills = Field(default_factory=HardSkills)
    dimension_scoring: DimensionScoring | None = None


# 维度定义**唯一来源**在 `app.core.dimensions.rubrics`（两侧共用一套维度 + 两套评分标准）。
# 这里只做 re-export，保证 `from app.core.resume_agent.schemas import TOP_DIMENSIONS` 仍然可用，
# 同时避免"学生侧一份、岗位侧又一份"的漂移（2026-09-27 P5 口径统一）。
TOP_DIMENSIONS = list(DIMENSION_ORDER)

SUB_DIMENSIONS: dict[str, list[str]] = {dim: list(subs) for dim, subs in DIMENSIONS.items()}

ALL_SUB_DIM_KEYS = [sub for subs in SUB_DIMENSIONS.values() for sub in subs]


class SubDimensionScores(BaseModel):
    score: float = Field(..., ge=1.0, le=5.0)
    sub_dimensions: dict[str, float] = Field(...)

    @field_validator("sub_dimensions")
    @classmethod
    def validate_sub_range(cls, v: dict[str, float]) -> dict[str, float]:
        for key, val in v.items():
            if not (1.0 <= val <= 5.0):
                raise ValueError(f"Sub-dimension '{key}' score {val} out of 1-5 range")
        return v


class DimensionScoring(BaseModel):
    profile_type: str = Field(default="candidate", pattern=r"^(candidate|job)$")
    total_dim_score: float = Field(..., ge=1.0, le=5.0)
    dimensions: dict[str, SubDimensionScores] = Field(...)

    @field_validator("dimensions")
    @classmethod
    def validate_all_six(
        cls, v: dict[str, SubDimensionScores]
    ) -> dict[str, SubDimensionScores]:
        missing = set(TOP_DIMENSIONS) - set(v.keys())
        if missing:
            raise ValueError(f"Missing top dimensions: {missing}")
        return v
