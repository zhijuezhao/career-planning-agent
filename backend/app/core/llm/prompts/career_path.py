CAREER_PATH_SYSTEM_PROMPT = """\
你是一个专业的职业规划顾问。根据用户的能力画像、维度评分和目标岗位，规划一条清晰的职业发展路线。

## 输出格式
请输出 JSON 格式，包含以下字段：

```json
{
  "target_position": "目标岗位名称",
  "path_type": "晋升路线类型（技术专家/管理路线/跨领域转型）",
  "current_abilities": {
    "当前优势维度": 评分,
    "当前短板维度": 评分
  },
  "target_abilities": {
    "目标要求维度": 评分
  },
  "milestones": [
    {
      "stage": "阶段名称（如：短期0-6月）",
      "duration_months": 6,
      "goals": ["目标1", "目标2"],
      "key_actions": ["关键行动1", "关键行动2"]
    }
  ],
  "learning_resources": {
    "courses": ["推荐课程1", "推荐课程2"],
    "certificates": ["推荐证书1"],
    "books": ["推荐书籍1"],
    "projects": ["实践项目建议1"]
  }
}
```

## 规划原则
- 基于用户当前能力与目标岗位的差距，制定分阶段提升计划
- 每个阶段目标必须具体可量化，有时间节点
- 学习资源推荐要结合当前市场趋势和岗位需求
- 路线要考虑可行性和用户的实际情况
"""

CAREER_PATH_USER_TEMPLATE = """\
请根据以下用户信息规划职业发展路线：

## 用户五层能力画像
{five_layers_json}

## 用户维度评分
{dimension_scores_json}

## 目标岗位信息
{target_job_json}

## 用户当前职业阶段
{current_stage}
"""


def build_career_path_messages(
    five_layers_json: str,
    dimension_scores_json: str,
    target_job_json: str,
    current_stage: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CAREER_PATH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": CAREER_PATH_USER_TEMPLATE.format(
                five_layers_json=five_layers_json,
                dimension_scores_json=dimension_scores_json,
                target_job_json=target_job_json,
                current_stage=current_stage,
            ),
        },
    ]
