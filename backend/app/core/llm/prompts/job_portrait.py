"""岗位画像提示词（六维口径，2026-09-27 P5 起）。

口径变更（用户拍板）
--------------------
- 画像的维度块从**英文五维**（technical/experience/soft_skills/education/responsibility）
  改为**中文六维**——与学生侧**同名同量程**（1–5），否则人岗匹配逐维对比对不上；
- 但**评分标准分侧**：这里评的是"**这个岗位要求多高**"（要求强度），
  学生侧评的是"这个人有多强"（能力水平）。两套标准的文字见
  `core/dimensions/rubrics.py::RUBRICS["job"]`（**数据**，改它就是迭代）；
- `key_skills`（关键技能清单）保留，挂在「专业技术能力」维度下（用户拍板）；
- **删掉了「晋升路径 / 转岗方向」两项**：按 §21 它们是**岗位信息**（由源表格的
  「岗位晋升」「换岗方向」列确定性解析写入 `career_path` / `transition_paths`），
  模型产了也不写库 = 白烧 token。它们最终的形态是**基于画像相似度的匹配**
  （用户 2026-09-27：晋升换岗一定要做，最后通过岗位画像的相似匹配来落地），
  届时用画像本身去算相似度，不需要模型在这里先猜一遍。
"""

from __future__ import annotations

from app.core.dimensions.rubrics import render_rubric

#: 六维的**机制**（键名/形状/硬性要求）与**评分标准**（`{rubric}`）分开写：
#: 标准那部分由数据渲染，键名这部分必须逐字稳定（历史教训：模型换键名 → 静默落默认值）。
JOB_PORTRAIT_SYSTEM_PROMPT = """\
你是一个专业的岗位画像分析师。根据提供的岗位结构化和清洗数据，生成一份深度岗位画像。

## 画像结构

### 1. 六维能力要求强度
对**这个岗位**给出六个维度的要求强度评分（1–5 分）与依据。
⚠️ 这是"**岗位要求多高**"，不是"某个人有多强"——两者的评分标准完全不同，见下方评分标准。

{rubric}

- 「专业技术能力」这一维**额外**给出 `key_skills`：该岗位要求的关键技能/技术栈清单（数组）；
- 其余五维只给 `score`（不需要 key_skills）。

### 2. 发展前景
- outlook: "朝阳" | "成熟" | "转型中"
- trend: 发展趋势简述
- risk_factors: 潜在风险因素（数组）

### 3. 画像摘要
- summary: 一段 100-200 字的总结，概述该岗位的特点和适合人群

## 输出要求
必须且仅输出一个合法 JSON 对象，不要包含任何额外文字或 markdown 代码块标记。

## 输出格式（⚠️ **顶层键名必须与本模板逐字一致**）
模型曾经把 `six_dimensions` 写成别的名字（早期版本还把 `summary` 写成 `profile_summary`、
把 `outlook` 写成 `development_outlook`）—— 键名一变，下游就取不到值、只能落回默认画像
（全 3 分/「成熟」/空摘要）。**所以键名不许改，也不许多包一层**：

{
  "six_dimensions": {
    "专业技术能力": {"score": 3, "key_skills": ["..."]},
    "实践经验背景": {"score": 3},
    "通用软素质":   {"score": 3},
    "职业匹配度":   {"score": 3},
    "成长潜力":     {"score": 3},
    "基础资质条件": {"score": 3}
  },
  "outlook": {"outlook": "成熟", "trend": "...", "risk_factors": ["..."]},
  "summary": "100-200 字的画像总结"
}

硬性要求：
- 六个维度**都要给 1-5 的整数 score**；不同维度要体现差异，**不要一律给 3**；
- 六维键名必须是：专业技术能力 / 实践经验背景 / 通用软素质 / 职业匹配度 / 成长潜力 / 基础资质条件；
- `summary` 必须是**非空**的一段文字（不许省略这个键）；
- `outlook.outlook` 只能是 "朝阳" | "成熟" | "转型中" 三者之一；
- 上面的 3 是**示例值**，请按岗位实际情况打分。
"""

JOB_PORTRAIT_USER_TEMPLATE = """\
请根据以下岗位数据生成深度画像：

## 岗位清洗数据
{job_data}
"""


def _rendered_system_prompt() -> str:
    # ⚠️ 用 `.replace` 而不是 `.format`：提示词里含 JSON 模板（大量 `{}`），format 会直接炸
    return JOB_PORTRAIT_SYSTEM_PROMPT.replace("{rubric}", render_rubric("job"))


def build_portrait_messages(job_data: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _rendered_system_prompt()},
        {"role": "user", "content": JOB_PORTRAIT_USER_TEMPLATE.format(job_data=job_data)},
    ]
