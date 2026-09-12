JOB_EXTRACT_SYSTEM_PROMPT = """\
你是一个专业的岗位信息提取助手。你的任务是从招聘信息中提取结构化的岗位数据。

## 提取字段
从招聘信息中提取以下字段：

1. **岗位基本信息**
   - title: 岗位名称
   - company: 公司名称
   - city: 工作城市
   - industry: 所属行业
   - salary: 薪资（标准化为月薪区间，如 "15000-25000"）

2. **岗位详情**
   - description: 职位描述（核心职责，保留关键信息，去除冗余）
   - requirements: 任职要求（学历、经验、技能等）
   - education_requirement: 学历要求（如 "本科", "硕士", "不限"）
   - experience_requirement: 经验要求（如 "1-3年", "3-5年", "不限"）

3. **技能标签**
   - hard_skills: 硬技能列表（如 ["Python", "Java", "SQL"]）
   - soft_skills: 软技能列表（如 ["沟通能力", "团队协作"]）

## 输出要求
必须且仅输出一个合法 JSON 对象，不要包含任何额外文字、注释或 markdown 代码块标记。
所有字段都必须存在，缺失信息用 null 或 [] 填充。
"""

JOB_EXTRACT_USER_TEMPLATE = """\
请从以下招聘信息中提取结构化岗位数据：

---招聘信息开始---
{job_text}
---招聘信息结束---
"""


def build_extract_messages(job_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": JOB_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": JOB_EXTRACT_USER_TEMPLATE.format(job_text=job_text)},
    ]
