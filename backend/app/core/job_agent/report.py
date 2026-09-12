"""Data quality report generation for the job import pipeline.

Provides a function to generate a Markdown report summarising the
quality of imported job data, including statistics on grading,
field completeness, and deduplication.
"""

from __future__ import annotations

from datetime import datetime


def generate_quality_report(
    total_input: int,
    total_passed: int,
    total_rejected: int,
    grade_distribution: dict[str, int] | None = None,
    field_completeness: dict[str, float] | None = None,
    dedup_stats: dict[str, int] | None = None,
    source: str = "unknown",
    extra_notes: list[str] | None = None,
) -> str:
    """Generate a data quality report in Markdown format.

    Args:
        total_input: Number of raw rows loaded from the source file.
        total_passed: Number of rows that passed quality grading (A/B/C).
        total_rejected: Number of rows graded D (rejected).
        grade_distribution: Map of grade -> count, e.g. {"A": 120, "B": 300, "C": 80, "D": 50}.
        field_completeness: Map of field name -> fill rate (0.0-1.0),
                            e.g. {"title": 1.0, "salary": 0.85}.
        dedup_stats: Map of dedup type -> count, e.g. {"exact": 10, "fuzzy": 25}.
        source: Data source description (e.g. filename).
        extra_notes: Additional observations about data quality.

    Returns:
        Markdown formatted report string.
    """
    passed_pct = round(total_passed / total_input * 100, 1) if total_input else 0.0
    rejected_pct = round(total_rejected / total_input * 100, 1) if total_input else 0.0

    lines = [
        "# 数据质量报告",
        "",
        f"> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> **数据源**：{source}",
        "",
        "---",
        "",
        "## 1. 导入概览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 原始输入行数 | {total_input} |",
        f"| 通过质量判定 (A/B/C) | {total_passed} ({passed_pct}%) |",
        f"| 被拒绝 (D级) | {total_rejected} ({rejected_pct}%) |",
        "",
    ]

    if grade_distribution:
        lines.extend([
            "## 2. 等级分布",
            "",
            "| 等级 | 数量 | 占比 |",
            "|------|------|------|",
        ])
        total_graded = sum(grade_distribution.values()) or 1
        for grade in ("A", "B", "C", "D"):
            count = grade_distribution.get(grade, 0)
            pct = round(count / total_graded * 100, 1)
            lines.append(f"| {grade} | {count} | {pct}% |")
        lines.append("")

    if dedup_stats:
        lines.extend([
            "## 3. 去重统计",
            "",
            "| 去重类型 | 去除数量 |",
            "|----------|----------|",
            f"| 精确去重（岗位编码） | {dedup_stats.get('exact', 0)} |",
            f"| 模糊去重（公司+岗位+城市） | {dedup_stats.get('fuzzy', 0)} |",
            "",
        ])

    if field_completeness:
        lines.extend([
            "## 4. 字段完整度",
            "",
            "| 字段 | 填充率 |",
            "|------|--------|",
        ])
        for field, rate in sorted(field_completeness.items()):
            bar_len = int(rate * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"| {field} | {bar} {round(rate * 100, 1)}% |")
        lines.append("")

    if extra_notes:
        lines.extend([
            "## 5. 质量备注",
            "",
        ])
        for note in extra_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "*报告由数据导入流水线自动生成*",
        "",
    ])

    return "\n".join(lines)
