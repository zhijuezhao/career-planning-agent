"""岗位综合画像卡提示词（B4-c，2026-10-03 用户拍板 **顺序 B**）。

用户原话::

    方案我想是通过大模型判断，进行综合性评估，从而取其精华去其糟粕，合成完整的岗位画像。

所以这一步的任务**不是**"给每条招聘打分"，而是**把一组招聘综合成一份代表性画像**：
提炼共性、保留分歧、显式丢弃噪音。

三条硬约束（都有血泪史，写在提示词里就是为了让模型别犯）：

1. **不许编**（用户 2026-10-03：「空值暂且保留，不自己编」）——
   一组里都没提供的字段，就留空/留 null，不要"合理推测"。
2. **必须显式说出丢了什么**（`excluded_noise`）——
   否则"去糟粕"无法复核：到底丢的是噪音还是重要信息，管理员看不到。
3. **键名必须逐字一致**——`portrait_builder` 的历史教训是模型换键名
   （`six_dimensions` → `five_dimension_ability`）导致下游静默落默认值。
   这里同样把模板钉死，并在 `aggregate.normalise_card()` 里留第二道防线。
"""

from __future__ import annotations

JOB_AGGREGATE_SYSTEM_PROMPT = """\
你是一个岗位数据综合分析专家。下面给你**同一个岗位、同一等级**的一批真实招聘记录
（可能是同一条招聘的多次抓取，也可能是不同公司招同一个岗位）。

你的任务：把它们**综合成一份代表作**——取其精华、去其糟粕，让这份结果能代表
"这个岗位、这个等级"的整体情况，而不是任何单条招聘的复述。

## 综合原则（必须遵守）

1. **只依据给定记录**：不要引入外部知识，不要"合理推测"记录里没有的信息。
   整组都没有提供的字段，就给 `null` 或空数组。
2. **提炼共性**：多数记录都提到的职责/要求/技能 → 放进 `consensus_*` / `core_skills`。
3. **保留分歧**：只有少数记录提到的 → 放进 `bonus_skills` / `differentiators`，
   **不要直接丢掉**。
4. **显式丢弃**：确实属于噪音（例如与岗位无关的公司介绍片段、明显的一次性活动文案）
   才丢，并且**必须在 `excluded_noise` 里写清楚丢了什么**，让人能复核你的判断。
5. **薪资**：给出整组的区间（不要只取一条）。原始薪资写法差异很大，以记录里的
   `薪资`（已归一化的月薪区间）为准。
6. **等级异议**：每条记录都带了「等级初判 / 等级依据」。如果你认为明显判错了，
   写进 `level_objections`（说明是哪几条、为什么）。没有异议就给空数组。
7. **技能要写成"最基础的技术名词"**（用户 2026-10-03 明确要求）：
   * `Java开发` / `Java语言` → 写 `Java`；`MySQL数据库` → 写 `MySQL`；
     `Spring Boot框架` → 写 `Spring Boot`；`Redis缓存` → 写 `Redis`；
   * **不要**带「开发/编程/框架/数据库/缓存/熟悉/掌握/精通」这类修饰词；
   * 但**不要**把专业名词削成更泛的词：`C/C++` 就写 `C/C++`（不是 `C`）、
     `项目管理工具` 就写 `项目管理工具`（不是 `项目管理`）。
8. **数量上限**：`core_skills` **最多 20 个**（只放高频、必会的），
   `bonus_skills` **最多 10 个**（放少数记录提到的，按重要度排序）。

## 输出要求

必须且仅输出一个合法 JSON 对象，不要任何额外文字或 markdown 代码块标记。

## 输出格式（⚠️ **顶层键名必须与下面逐字一致，不许多包一层、不许改名**）

{
  "role": "岗位名（照抄输入里的岗位名）",
  "level": "等级（照抄本次的等级）",
  "posting_count": 12,
  "consensus_duties": ["多数记录都提到的职责"],
  "consensus_requirements": ["多数记录都提到的要求（学历/经验/技能门槛）"],
  "core_skills": ["核心技能（高频、必会）"],
  "bonus_skills": ["加分技能（少数记录提到，保留不丢）"],
  "salary_range": {"envelope": "4000-15000", "median": "6000-9000"},
  "education_range": "大专~硕士（没有就 null）",
  "experience_range": "应届~3年（没有就 null）",
  "city_distribution": ["北京", "上海"],
  "top_companies": ["出现较多的公司名"],
  "differentiators": ["组内显著差异（如：部分岗位需赴日、部分为实习岗）"],
  "excluded_noise": ["我丢弃了什么、为什么（没有就空数组）"],
  "level_objections": ["哪几条等级初判可能不对、为什么（没有就空数组）"]
}

硬性要求：
- 所有键都必须出现（没有内容就给 `[]` 或 `null`，**不许省略键**）；
- 数组类字段必须是数组，**不许写成字符串**；
- `role` / `level` / `posting_count` 必须与输入一致，不要自己改；
- 不要输出任何解释性文字，只输出 JSON。
"""

JOB_AGGREGATE_USER_TEMPLATE = """\
请把以下**同一岗位、同一等级**的 {count} 条招聘记录综合成一份代表性画像卡。

岗位名：{role}
等级：{level}

## 招聘记录（每行一个 JSON）
{group_input}
"""


def build_aggregate_messages(
    group_input: str, *, role: str, level: str, count: int
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": JOB_AGGREGATE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": JOB_AGGREGATE_USER_TEMPLATE.format(
                count=count, role=role, level=level, group_input=group_input
            ),
        },
    ]
