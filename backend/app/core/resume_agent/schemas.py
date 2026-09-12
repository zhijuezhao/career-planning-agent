from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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


TOP_DIMENSIONS = [
    "专业技术能力",
    "实践经验背景",
    "通用软素质",
    "职业匹配度",
    "成长潜力",
    "基础资质条件",
]

SUB_DIMENSIONS: dict[str, list[str]] = {
    "专业技术能力": ["核心专业技能", "工具与技术栈"],
    "实践经验背景": ["相关经历匹配度", "实践深度与产出"],
    "通用软素质": ["沟通协作能力", "问题解决能力", "责任心与执行力"],
    "职业匹配度": ["方向与行业匹配", "地域与薪资匹配"],
    "成长潜力": ["学习能力", "进取心与可塑性"],
    "基础资质条件": ["学历与专业对口", "资质认证"],
}

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
