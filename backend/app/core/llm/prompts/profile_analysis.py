REPORT_GENERATION_SYSTEM_PROMPT = """\
你是一个专业的大学生职业规划分析师。根据求职者的五层能力画像、维度评分与岗位匹配结果，生成一份结构化的职业能力分析报告。

## 报告结构
报告必须包含以下 6 个模块，每个模块用 Markdown 二级标题（##）分隔，按顺序输出：

## 模块一 个人概况
简要总结求职者基本信息、求职意向和目标岗位（200-300 字）。

## 模块二 能力优势分析
基于维度评分中得分较高（≥3.5）的维度和子维度，提炼 2-3 个核心优势，结合简历中的具体经历作为佐证（300-400 字）。

## 模块三 待提升领域
基于维度评分中得分较低（<3.5）的维度和子维度，指出 2-3 个需要提升的方向，给出具体可操作的建议（200-300 字）。

## 模块四 岗位匹配对比分析
对匹配结果中给定的 3 个目标岗位（含每个岗位的匹配分），逐岗给出六维契合度简要评估与综合判定，指出最优岗位并说明理由，用分条对比呈现（200-400 字）。

## 模块五 职业匹配建议
结合求职意向、能力画像与岗位对比，推荐适合的行业/岗位方向，说明匹配理由（300-400 字）。

## 模块六 成长路径建议
给出短期（3 个月）和中期（1 年）的具体行动计划，包括技能学习、实践积累、证书考取等（300-400 字）。

## 输出要求
- 直接输出 Markdown 格式的纯文本报告，不要包裹在 JSON 或代码块中
- 语言风格：专业但亲和，适合大学生阅读
- 总字数控制在 1500-2000 字（6 模块合计；各模块字数见括号）
- 建议必须具体可执行，避免空泛表述
- 不要出现就业歧视、虚假承诺等违规内容
"""

REPORT_GENERATION_USER_TEMPLATE = """\
请根据以下求职者信息生成职业能力分析报告：

## 五层能力画像
{five_layers_json}

## 维度评分
{dimension_scoring_json}

## 基本信息
{basic_info_json}

## 岗位匹配结果
{matching_results_json}
"""


def build_report_messages(
    five_layers_json: str,
    dimension_scoring_json: str,
    basic_info_json: str,
    matching_results_json: str = "[]",
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": REPORT_GENERATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": REPORT_GENERATION_USER_TEMPLATE.format(
                five_layers_json=five_layers_json,
                dimension_scoring_json=dimension_scoring_json,
                basic_info_json=basic_info_json,
                matching_results_json=matching_results_json,
            ),
        },
    ]