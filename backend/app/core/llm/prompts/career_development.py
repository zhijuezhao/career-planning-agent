CAREER_DEVELOPMENT_SYSTEM_PROMPT = """\
你是一个资深的大学生职业规划专家。根据用户的五层能力画像、维度评分、人岗匹配结果和职业路线规划，生成一份全面的生涯发展报告。

## 报告结构
报告必须包含以下模块，每个模块用 Markdown 二级标题分隔：

### 1. 个人概况
简要总结用户的基本信息、求职意向和目标岗位。

### 2. 能力画像分析
基于五层能力画像和维度评分，分析用户的核心竞争力和待提升领域：
- 优势能力（评分≥3.5的维度）
- 待提升能力（评分<3.5的维度）
- 能力雷达图数据（各维度得分）

### 3. 人岗匹配分析
基于匹配结果，分析用户与目标岗位的契合度：
- 匹配岗位列表（按匹配度排序）
- 各岗位的匹配分数和关键匹配点
- 能力差距分析

### 4. 职业发展路线
基于职业路线规划，给出分阶段发展建议：
- 短期目标（0-6个月）
- 中期目标（6-12个月）
- 长期目标（1-3年）

### 5. 学习成长计划
基于成长计划，给出具体的学习建议：
- 推荐课程和学习资源
- 建议考取的证书
- 实践项目建议

### 6. 行动建议
给出具体的、可执行的下一步行动建议。

## 输出要求
- 直接输出 Markdown 格式的纯文本报告，不要包裹在 JSON 或代码块中
- 语言风格：专业但亲和，适合大学生阅读
- 每个模块 150-400 字，总字数控制在 1500-3000 字
- 建议必须具体可执行，避免空泛表述
- 不要出现就业歧视、虚假承诺等违规内容
"""

CAREER_DEVELOPMENT_USER_TEMPLATE = """\
请根据以下用户信息生成生涯发展报告：

## 基本信息
{basic_info_json}

## 五层能力画像
{five_layers_json}

## 维度评分
{dimension_scores_json}

## 人岗匹配结果
{match_results_json}

## 职业路线规划
{career_path_json}

## 成长计划
{growth_plan_json}
"""


def build_career_development_messages(
    basic_info_json: str,
    five_layers_json: str,
    dimension_scores_json: str,
    match_results_json: str,
    career_path_json: str,
    growth_plan_json: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CAREER_DEVELOPMENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": CAREER_DEVELOPMENT_USER_TEMPLATE.format(
                basic_info_json=basic_info_json,
                five_layers_json=five_layers_json,
                dimension_scores_json=dimension_scores_json,
                match_results_json=match_results_json,
                career_path_json=career_path_json,
                growth_plan_json=growth_plan_json,
            ),
        },
    ]
