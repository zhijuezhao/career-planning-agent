from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.job_agent.levels import LEVEL_UNLIMITED
from app.infrastructure.database import Base

# 岗位去重键的标题部分（P2）：生成列，DDL 的唯一来源见 apply_ddl.py / core/dedup_keys.py
_TITLE_KEY_EXPR = "lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))"


class JobProfile(Base):
    __tablename__ = "job_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # B4（2026-10-03）：唯一键从 `(title_key)` 变成 **`(title_key, level)`**
    # （`uq_job_profiles_title_level`）—— 「岗位名 × 等级」各一条画像，
    # 因为用户要的是"综合出岗位信息后按规则划分出初级/中级/高级"，三份画像各有其位。
    # 生成列由数据库算，**不可写**（`Computed` 让 SQLAlchemy 把它排除在 INSERT/UPDATE 之外）。
    title_key: Mapped[str | None] = mapped_column(
        String(200), Computed(_TITLE_KEY_EXPR, persisted=True)
    )
    industry: Mapped[str | None] = mapped_column(String(100))
    #: 岗位等级（初级/中级/高级/不限）。
    #: ⚠️ **NOT NULL + 默认「不限」**：唯一索引里 NULL 互不相等，可空的话
    #: 两条 level=NULL 的同名岗位不会冲突 → 又不分等级了（P2 在 `(title, null)` 上踩过）。
    level: Mapped[str] = mapped_column(
        String(20), nullable=False, default=LEVEL_UNLIMITED, server_default=LEVEL_UNLIMITED
    )
    hard_skills: Mapped[dict | None] = mapped_column(JSONB)
    soft_skills: Mapped[dict | None] = mapped_column(JSONB)
    salary_range: Mapped[str | None] = mapped_column(String(50))
    education_requirement: Mapped[str | None] = mapped_column(String(50))
    experience_requirement: Mapped[str | None] = mapped_column(String(100))
    career_path: Mapped[dict | None] = mapped_column(JSONB)
    transition_paths: Mapped[dict | None] = mapped_column(JSONB)
    # P4a（2026-09-27）：所需证书。来源是职业发展路线表的「所需证书」列 ——
    # 它此前**没有字段可落**（只并进了 requirements 文本），由 `career_fields.py` 确定性回填。
    certificates: Mapped[list | None] = mapped_column(JSONB)
    requirement_intensity: Mapped[dict | None] = mapped_column(JSONB)
    outlook: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    source_data_ids: Mapped[dict | None] = mapped_column(JSONB)
    # B3-1（2026-09-27）：两列此前**只在 DDL 里存在、ORM 没映射**
    # （`apply_ddl.py:260-269` 早已 ADD COLUMN），所以任何代码都写不进也读不出。
    # 现在补上映射 —— 没有任何 DDL 改动。
    #: 该岗位的招聘来源链接（表格「岗位链接」列或链接富化命中的 URL）
    source_url: Mapped[str | None] = mapped_column(Text)
    #: 链接富化的逐行统计（命中的层级/填充了哪些字段/冲突/provenance）
    enrich_stats: Mapped[dict | None] = mapped_column(JSONB)
    # ── B4（2026-10-03）：分等级画像的两列 ──────────────────────────────────────
    #: 薪资统计（用户要求"两者都存"）：`{envelope, median, raw, n, sources}`。
    #: `salary_range` 是 String(50)，存不下"包络区间 + 中位数区间 + 原文"三份。
    salary_stats: Mapped[dict | None] = mapped_column(JSONB)
    #: 该 (岗位名, 等级) 组的 **LLM 综合画像卡** —— 落库才可审计：
    #: 综合了哪几条招聘、`excluded_noise` 丢了什么、模型对等级初判的异议、
    #: 提示词版本与生成时间（"只重跑聚合"时用来对比）。
    aggregate_card: Mapped[dict | None] = mapped_column(JSONB)
    # ⚠️ 这里**没有** `company_id`（B2-2 加过、2026-09-27 任务 3 删除）：
    # 岗位↔公司是多对多，"谁在招谁"的唯一真相是 `job_company_links`。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobRawData(Base):
    __tablename__ = "job_raw_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(50))
    salary: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: B4（2026-10-03）：原始行全量 + 抽取结果。
    #:
    #: 两个用途：
    #: 1) **聚合阶段的数据来源** —— `job_raw_data` 只有下面这十列，
    #:    抽取器的 `hard_skills`/`soft_skills`/`education_requirement`/
    #:    `experience_requirement`/`level` 与原始表的 `岗位编码`/区县/`公司类型`/
    #:    `公司详情`/`更新日期` 都没有列可放；逐行 upsert 时就被丢掉了，
    #:    聚合阶段读不到东西就无从"综合"。
    #: 2) **审计** —— 「这条 raw 对应哪个原始招聘」（按 `岗位编码`）可反查。
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
