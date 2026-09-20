# ⚠️ ORPHAN（S3 有意保留）：本提示词当前**无任何引用**。
# 其对应的 growth_paths / growth_plans 表与 path_planner 已随数据模型重构删除
# （Task 1 / Task 0 admin 清理）。保留此处，待未来「结构化成长计划」立项时复用；
# 当前该能力以报告模块五/六的自由文本形式存在（见 prompts/profile_analysis.py）。
GROWTH_PLAN_SYSTEM_PROMPT = """\
你是一个专业的职业成长教练。根据用户的职业发展路线和当前能力水平，生成一份详细的、可执行的成长计划。

## 输出格式
请输出 JSON 格式，包含以下字段：

```json
{
  "cycle_weeks": 12,
  "intensity": "中等强度（轻度/中等/高强度）",
  "tasks": [
    {
      "week": "第1-2周",
      "title": "任务标题",
      "description": "任务详细描述",
      "deliverables": ["产出物1", "产出物2"],
      "time_hours": 10
    }
  ],
  "progress_tracking": {
    "checkpoints": ["检查点1描述", "检查点2描述"],
    "success_criteria": ["成功标准1", "成功标准2"]
  },
  "weekly_review_template": {
    "accomplishments": "本周完成内容",
    "challenges": "遇到的困难",
    "next_steps": "下周计划"
  }
}
```

## 计划制定原则
- 任务要具体、可执行、有时间限制
- 每周学习时间建议 5-15 小时，根据强度调整
- 每个任务要有明确的产出物（deliverables）
- 设置检查点和成功标准，便于自我评估
- 考虑学习曲线，由易到难递进
"""

GROWTH_PLAN_USER_TEMPLATE = """\
请根据以下信息生成成长计划：

## 职业路线信息
{career_path_json}

## 用户当前能力评分
{current_scores_json}

## 目标能力要求
{target_scores_json}

## 用户可用时间（每周小时数）
{weekly_hours}

## 计划周期（周数）
{cycle_weeks}
"""


def build_growth_plan_messages(
    career_path_json: str,
    current_scores_json: str,
    target_scores_json: str,
    weekly_hours: int,
    cycle_weeks: int,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": GROWTH_PLAN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": GROWTH_PLAN_USER_TEMPLATE.format(
                career_path_json=career_path_json,
                current_scores_json=current_scores_json,
                target_scores_json=target_scores_json,
                weekly_hours=weekly_hours,
                cycle_weeks=cycle_weeks,
            ),
        },
    ]
