"""内容安全过滤模块单元测试。"""

from __future__ import annotations

from app.core.safety import (
    DISCLAIMER,
    ContentSafetyFilter,
    ViolationType,
    append_disclaimer,
    check_content,
)

# ---------- 安全文本 ----------

def test_safe_text_passes():
    f = ContentSafetyFilter()
    result = f.check("负责前端页面开发，熟悉 Vue，本科以上学历，团队协作良好")
    assert result.is_safe is True
    assert result.violation_type is None
    assert result.reason is None


def test_empty_text_is_safe():
    assert ContentSafetyFilter().check("").is_safe is True


def test_is_safe_bool_helper():
    f = ContentSafetyFilter()
    assert f.is_safe("正常岗位描述") is True
    assert f.is_safe("仅限男性") is False


# ---------- 歧视类违规 ----------

def test_gender_discrimination_detected():
    result = ContentSafetyFilter().check("本岗位仅限男性应聘")
    assert result.is_safe is False
    assert result.violation_type == ViolationType.DISCRIMINATION
    assert result.matched_text == "仅限男性"
    assert "性别限制" in result.reason


def test_region_discrimination_detected():
    result = ContentSafetyFilter().check("不招外地人员")
    assert result.is_safe is False
    assert result.violation_type == ViolationType.DISCRIMINATION
    assert result.matched_text == "不招外地"


def test_marriage_discrimination_detected():
    result = ContentSafetyFilter().check("要求未婚未育")
    assert result.is_safe is False
    assert result.violation_type == ViolationType.DISCRIMINATION


# ---------- 虚假承诺类违规 ----------

def test_false_promise_detected():
    result = ContentSafetyFilter().check("加入我们，保证录取")
    assert result.is_safe is False
    assert result.violation_type == ViolationType.FALSE_PROMISE
    assert result.matched_text == "保证录取"


def test_absolute_success_detected():
    result = ContentSafetyFilter().check("100%通过面试")
    assert result.is_safe is False
    assert result.violation_type == ViolationType.FALSE_PROMISE


def test_first_violation_wins():
    # 歧视规则排在虚假承诺之前，含两类违规时应返回首个命中（歧视）
    result = ContentSafetyFilter().check("仅限男性，且保证录取")
    assert result.violation_type == ViolationType.DISCRIMINATION


# ---------- 免责声明 ----------

def test_append_disclaimer():
    text = "这是一段职业建议"
    out = ContentSafetyFilter().append_disclaimer(text)
    assert out == text + DISCLAIMER


def test_append_disclaimer_idempotent():
    f = ContentSafetyFilter()
    once = f.append_disclaimer("建议内容")
    twice = f.append_disclaimer(once)
    assert once == twice  # 已包含则不重复追加


def test_custom_disclaimer():
    f = ContentSafetyFilter(disclaimer="\n[自定义声明]")
    assert f.append_disclaimer("内容") == "内容\n[自定义声明]"


# ---------- sanitize 组合 ----------

def test_sanitize_safe_appends_disclaimer():
    result, text = ContentSafetyFilter().sanitize("正常的职业规划建议")
    assert result.is_safe is True
    assert text.endswith(DISCLAIMER.strip()) or DISCLAIMER in text


def test_sanitize_unsafe_returns_original():
    original = "仅限男性的岗位"
    result, text = ContentSafetyFilter().sanitize(original)
    assert result.is_safe is False
    assert text == original  # 不安全时不追加、原样返回


# ---------- 模块级便捷函数 ----------

def test_module_level_check_content():
    assert check_content("正常内容").is_safe is True
    assert check_content("保证录取").is_safe is False


def test_module_level_append_disclaimer():
    assert append_disclaimer("内容") == "内容" + DISCLAIMER


# ---------- 枚举 ----------

def test_violation_type_enum_values():
    assert ViolationType.DISCRIMINATION == "discrimination"
    assert ViolationType.FALSE_PROMISE == "false_promise"
