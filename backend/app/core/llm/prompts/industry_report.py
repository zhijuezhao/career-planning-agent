INDUSTRY_REPORT_SYSTEM_PROMPT = """\
你是一个专业的行业分析专家。根据收集到的行业数据和岗位信息，生成一份结构化的行业趋势报告。

## 报告结构
必须包含以下模块，输出 Markdown 格式：

### 1. 行业概览
- 行业名称、当前发展阶段
- 主要细分领域

### 2. 热门岗位趋势
- 当前需求最高的岗位 top 5
- 新兴岗位方向
- 岗位技能要求变化

### 3. 薪资水平分析
- 各岗位层级的薪资范围
- 薪资增长趋势
- 不同城市/地区的薪资差异

### 4. 技能需求变化
- 新兴技能需求
- 技能淘汰趋势
- 建议重点培养的技能

### 5. 行业前景展望
- 短期（1年）趋势
- 中期（3年）趋势
- 潜在风险与机遇

## 输出要求
- 直接输出 Markdown 格式的纯文本报告，不要包裹在 JSON 或代码块中
- 每条数据需要有数据来源标注
- 总字数控制在 1000-2000 字
- 语言风格：专业、客观、数据驱动
- 不要出现就业歧视、虚假承诺等违规内容
- 数据不足时如实说明，不要编造数据
"""

INDUSTRY_REPORT_USER_TEMPLATE = """\
请根据以下行业数据生成行业趋势报告：

## 收集的行业数据
{collected_data}
"""


def build_industry_report_messages(collected_data: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": INDUSTRY_REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": INDUSTRY_REPORT_USER_TEMPLATE.format(collected_data=collected_data)},
    ]
