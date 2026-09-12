"""内容安全过滤模块。

对 LLM 生成或用户输入的职业内容做合规检查，覆盖两类主要风险：
- 就业歧视表述（性别 / 地域 / 婚育状况）
- 虚假承诺表述（保证录取、绝对化成功率）

并提供免责声明自动追加，满足合规要求。规则为启发式正则，
可按需在 _RULES 中扩展；本模块提供的是可复用的检查框架，而非穷举式敏感词库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ViolationType(str, Enum):
    """违规类型。"""

    DISCRIMINATION = "discrimination"  # 就业歧视
    FALSE_PROMISE = "false_promise"  # 虚假承诺


DISCLAIMER = "\n\n---\n*以上内容仅供参考，不构成就业承诺或专业职业咨询意见。*"

# 规则表：(违规类型, 已编译正则, 人类可读描述)
_RULES: list[tuple[ViolationType, re.Pattern[str], str]] = [
    (
        ViolationType.DISCRIMINATION,
        re.compile(r"(仅限|只要|优先|限)(男性|女性|男生|女生|男士|女士)"),
        "性别限制",
    ),
    (
        ViolationType.DISCRIMINATION,
        re.compile(r"(不招|拒绝|排除|勿扰)(外地|外省|某省|某地|少数)"),
        "地域歧视",
    ),
    (
        ViolationType.DISCRIMINATION,
        re.compile(r"(必须|要求|限)(未婚|未育|无子女|已婚已育)"),
        "婚育状况限制",
    ),
    (
        ViolationType.FALSE_PROMISE,
        re.compile(r"(保证|确保|一定|肯定|包)(能|会|可)?(找到|获得|入职|录取|通过|offer)"),
        "就业保证承诺",
    ),
    (
        ViolationType.FALSE_PROMISE,
        re.compile(r"(百分百|100%|完全)(成功|通过|录用|上岸)"),
        "绝对化成功率",
    ),
]


@dataclass
class SafetyResult:
    """检查结果。"""

    is_safe: bool
    violation_type: ViolationType | None = None
    reason: str | None = None
    matched_text: str | None = None


class ContentSafetyFilter:
    """内容安全过滤器。无状态，可用类实例或模块级便捷函数。"""

    def __init__(self, disclaimer: str = DISCLAIMER):
        self._disclaimer = disclaimer

    def check(self, text: str) -> SafetyResult:
        """检查文本是否安全，命中首个违规即返回结构化结果。"""
        if not text:
            return SafetyResult(is_safe=True)
        for violation_type, pattern, desc in _RULES:
            match = pattern.search(text)
            if match:
                return SafetyResult(
                    is_safe=False,
                    violation_type=violation_type,
                    reason=f"检测到{desc}表述",
                    matched_text=match.group(0),
                )
        return SafetyResult(is_safe=True)

    def is_safe(self, text: str) -> bool:
        """便捷布尔判定。"""
        return self.check(text).is_safe

    def append_disclaimer(self, text: str) -> str:
        """追加免责声明（幂等：已包含则不重复追加）。"""
        marker = self._disclaimer.strip()
        if marker and marker in text:
            return text
        return text + self._disclaimer

    def sanitize(self, text: str) -> tuple[SafetyResult, str]:
        """组合便捷方法：检查 + 若安全则追加免责声明。

        返回 (检查结果, 处理后文本)。不安全时文本原样返回，由调用方决定拦截或改写。
        """
        result = self.check(text)
        if result.is_safe:
            return result, self.append_disclaimer(text)
        return result, text


# 模块级默认单例与便捷函数
_default_filter = ContentSafetyFilter()


def check_content(text: str) -> SafetyResult:
    """使用默认过滤器检查文本。"""
    return _default_filter.check(text)


def append_disclaimer(text: str) -> str:
    """使用默认过滤器追加免责声明。"""
    return _default_filter.append_disclaimer(text)


__all__ = [
    "DISCLAIMER",
    "ContentSafetyFilter",
    "SafetyResult",
    "ViolationType",
    "append_disclaimer",
    "check_content",
]
