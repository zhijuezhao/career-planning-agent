"""P4a：职业字段的确定性解析（`core/job_agent/career_fields.py`）与回填结果。

两层断言：
1. **纯函数层**：解析规则（尤其是"证书按 `、` 切、不能按 `/` 切"这个坑）；
2. **数据层**：回填后 `job_profiles` 的三列必须**与源文本解析结果一致**——
   证明"落库的值 = 源文本说的值"，而不是随手写了个非空值糊过去。
"""

from __future__ import annotations

import asyncio

import pytest
from app.core.job_agent.career_fields import (
    FIELD_LABELS,
    extract_career_fields,
    looks_suspicious,
    parse_labelled_list,
)
from app.domain.models.job import JobProfile, JobRawData
from sqlalchemy import select
from tests.conftest import test_session_factory


def _parsed_has_career_labels(description: str | None, requirements: str | None) -> bool:
    """这份源文本里到底有没有「岗位晋升 / 换岗方向 / 所需证书」标签？

    用来区分两种数据：
    * **职业发展路线表**（`#853` 那 82 行）—— 源文本带这些标签 → 三列**必须**回填；
    * **智联招聘岗位表**（2026-10-04 导入的 524 行）—— 只有职责/要求 → 源里没有这些信息，
      三列**本来就该为空**（要求非空等于要求系统造数据）。

    ⚠️ 用 `looks_suspicious` 过滤过的值才算数 —— 与回填脚本同一口径，
    否则"某个字段名恰好出现在长文本里"会被当成有标签。
    """
    parsed = extract_career_fields(description, requirements)
    for field_name in ("career_path", "certificates"):
        items = parsed.get(field_name) or []
        if items and not looks_suspicious(items, field_name):
            return True
    return False

# 与真实数据同形的两条文本（实测 84/84 行格式一致）
DESCRIPTION = "岗位晋升：全栈工程师 / 技术经理\n换岗方向：测试开发工程师 / Python / 数据工程师"
REQUIREMENTS = (
    "核心技能：Java（Java 8+ Stream/Lambda/JUC）、Spring Boot/Spring Cloud、Redis\n"
    "所需证书：软考（软件设计师/系统架构师）、Oracle Java认证（OCP/OCM）、Spring Certified Professional"
)


class TestParseLabelledList:
    def test_career_path(self):
        assert parse_labelled_list(DESCRIPTION, "career_path") == ["全栈工程师", "技术经理"]

    def test_transition_paths(self):
        assert parse_labelled_list(DESCRIPTION, "transition_paths") == [
            "测试开发工程师",
            "Python",
            "数据工程师",
        ]

    def test_certificates_split_by_ideographic_comma_not_slash(self):
        """⚠️ 核心坑：证书名**内部含 `/`**（`软考（软件设计师/系统架构师）`）。

        若按 `/` 切，一项会被切成两项（`软考（软件设计师` + `系统架构师）`）。
        """
        assert parse_labelled_list(REQUIREMENTS, "certificates") == [
            "软考（软件设计师/系统架构师）",
            "Oracle Java认证（OCP/OCM）",
            "Spring Certified Professional",
        ]

    def test_label_is_line_scoped(self):
        """`岗位晋升` 的取值不能把下一行的 `换岗方向` 一起吃进去。"""
        assert "换岗方向" not in "".join(parse_labelled_list(DESCRIPTION, "career_path"))

    def test_halfwidth_colon_and_trailing_punctuation(self):
        assert parse_labelled_list("岗位晋升: 高级前端 / 前端架构师。", "career_path") == [
            "高级前端",
            "前端架构师",
        ]

    def test_missing_label_and_empty_input(self):
        assert parse_labelled_list(DESCRIPTION, "certificates") == []
        assert parse_labelled_list(None, "career_path") == []
        assert parse_labelled_list("", "career_path") == []

    def test_unknown_field_raises(self):
        """字段名写错是代码 bug，不该被静默吞掉。"""
        try:
            parse_labelled_list(DESCRIPTION, "not_a_field")
        except KeyError:
            return
        raise AssertionError("未知字段名应该抛 KeyError")


class TestExtractCareerFields:
    def test_returns_only_found_fields(self):
        found = extract_career_fields(DESCRIPTION, REQUIREMENTS)
        assert set(found) == {"career_path", "transition_paths", "certificates"}
        assert extract_career_fields("无关文本", None) == {}

    def test_no_false_positive_on_plain_text(self):
        assert extract_career_fields("核心技能：Java、Redis", "普通要求") == {}


class TestLooksSuspicious:
    def test_normal_items_are_fine(self):
        assert not looks_suspicious(["高级前端", "前端架构师"], "career_path")
        # 证书里的 `/` 是**合法**的（不带空格），不能误判
        assert not looks_suspicious(["软考（软件设计师/系统架构师）"], "certificates")

    def test_unseparated_blob_is_suspicious(self):
        """分隔符没生效 → 整段一项。它通常**超长**，这条靠长度兜住。"""
        blob = "全栈工程师 / 技术经理 / 架构师 / " * 6
        assert len(blob) > 80
        assert looks_suspicious([blob], "career_path")

    def test_residual_other_separator_is_suspicious(self):
        assert looks_suspicious(["软考、Oracle认证"], "career_path")


class TestBackfilledData:
    """数据层：三列必须与源文本解析结果一致（P4a 的回填事实）。"""

    @staticmethod
    def _load():
        async def _query():
            async with test_session_factory() as session:
                profiles = (
                    await session.execute(select(JobProfile).order_by(JobProfile.id))
                ).scalars().all()
                raws = (await session.execute(select(JobRawData))).scalars().all()
                return profiles, raws

        return asyncio.run(_query())

    def test_all_profiles_have_career_path_and_certificates(self):
        """**源文本里写了职业字段的**岗位，三列必须落库且非空。

        ⚠️ 不能要求"所有导入岗位都非空"（2026-10-04 修正）：这三列由 `career_fields.py`
        从源文本里的 `岗位晋升：/ 换岗方向：/ 所需证书：` 标签**确定性解析**得到，
        而这些标签只存在于**职业发展路线表**那个数据集。本次真实导入的智联招聘表
        （524 行 × 12 列）只有岗位职责/任职要求 —— 源里根本没有这些信息，
        实测对这批数据跑回填脚本「可解析 0 处」。要求它非空等于要求系统凭空造数据。

        所以断言分两层：
        ① 所有导入岗位这三列都必须是**数组**（接口契约，前端按数组渲染）；
        ② **凡源文本里能解析出职业字段的**，必须真的落库且非空。

        ⚠️ 只检查"有同名 `job_raw_data` 行"的岗位（= 真导入数据）：测试自己 upsert 出来的
        岗位没有原始行，不该被这条断言波及（否则一跑测试就红，属测试卫生问题）。
        """
        profiles, raws = self._load()
        if not profiles:
            pytest.skip("库里没有岗位数据")

        by_title: dict[str, list] = {}
        for raw in raws:
            by_title.setdefault(raw.title, []).append(raw)
        imported = [p for p in profiles if p.title in by_title]
        if not imported:
            pytest.skip("库里没有可追溯的导入岗位")

        # ① 类型契约（空值有两种合法形态：SQL NULL / JSON null → Python None，或空数组 []）
        for profile in imported:
            assert profile.career_path is None or isinstance(profile.career_path, list), (
                f"{profile.title} 的 career_path 既不是数组也不是空：{profile.career_path!r}"
            )
            assert profile.certificates is None or isinstance(profile.certificates, list), (
                f"{profile.title} 的 certificates 既不是数组也不是空：{profile.certificates!r}"
            )

        # ② 源文本里有标签的，必须非空
        with_labels = [
            profile
            for profile in imported
            if any(
                _parsed_has_career_labels(raw.description, raw.requirements)
                for raw in by_title[profile.title]
            )
        ]
        if not with_labels:
            pytest.skip(
                "当前数据集的源文本里没有「岗位晋升/换岗方向/所需证书」标签"
                "（如智联招聘表）→ 无内容可回填，这条不适用"
            )
        for profile in with_labels:
            assert profile.career_path, f"{profile.title} 的源文本有职业字段，但 career_path 为空"
            assert profile.certificates, f"{profile.title} 的源文本有职业字段，但 certificates 为空"

    def test_stored_values_equal_source_text_parse(self):
        """逐条对账：**本次回填写入的值 == 源文本解析值**。

        - `career_path` / `certificates` 回填前是 **0/82** → 这 82 条全是本次写的，
          必须与源文本**逐字一致**（这是解析器没悄悄失效的硬证据）。
        - `transition_paths` 回填前已有 **8 条**内容（LLM/早期导入产物，例如 `Python`
          的旧值是 `Java后端工程师`，而源文本写的是 `Java`）。回填是**只填空**，
          所以这 8 条按设计被保留 —— 这里只要求它们非空，并确认"保留的只是少数"
          （否则说明回填根本没生效）。
        """
        profiles, raws = self._load()
        if not profiles:
            pytest.skip("库里没有岗位数据")
        if not raws:
            pytest.skip("库里没有原始数据（job_raw_data 为空）→ 无对账基准")

        by_title: dict[str, list[tuple[str | None, str | None]]] = {}
        for raw in raws:
            by_title.setdefault(raw.title, []).append((raw.description, raw.requirements))

        with_labels = 0
        checked = 0
        for profile in profiles:
            sources = by_title.get(profile.title)
            if not sources:
                continue
            checked += 1
            expected: dict[str, list[str]] = {}
            for description, requirements in sources:
                for field_name, items in extract_career_fields(description, requirements).items():
                    bucket = expected.setdefault(field_name, [])
                    for item in items:
                        if item not in bucket:
                            bucket.append(item)

            # 三列都是**源文本确定性解析**的产物 → 双向对账：
            #   源里有 → 库里必须逐字一致（回填写的就是它）；
            #   源里没有 → 库里必须为空（**不许凭空有值**）。
            # ⚠️ 原实现写死 `expected[field_name]`（源里没有就 KeyError）并要求
            #    `transition_paths` 非空 —— 那是**职业发展路线表**专属假设。本次导入的
            #    智联招聘表源文本里没有这些标签（实测三列全空、回填脚本「可解析 0 处」），
            #    旧断言会把"源里本来就没有"误判成"回填没生效"。
            for field_name in ("career_path", "certificates", "transition_paths"):
                stored_value = getattr(profile, field_name)
                source_value = expected.get(field_name, [])
                if source_value:
                    with_labels += 1
                    assert stored_value == source_value, (
                        f"{profile.title} 的 {field_name} 与源文本不一致："
                        f"库={stored_value!r} 源={source_value!r}"
                    )
                else:
                    assert not stored_value, (
                        f"{profile.title} 的 {field_name} 源文本里没有，库里却写着 {stored_value!r}"
                    )

        if checked == 0:
            # 与 `test_all_profiles_have_career_path_and_certificates` 同一套口径：
            # 库里只剩"测试自己 upsert 的岗位"（没有可追溯的导入行）时无从对账 → 跳过，
            # 而不是拿 `assert checked >= 1` 报红（2026-09-27：清库后暴露的测试卫生问题）。
            pytest.skip("库里没有可追溯的导入岗位（与 job_raw_data 对不上）")

        # 至少要真对过一条账（否则说明过滤口径把数据全排除了）
        assert checked >= 1
        # `with_labels` 在智联招聘表上整表为 0（源里没有这些标签）—— 属**正常**，
        # 不是"回填没生效"；回填是否生效由上面的双向对账保证。
        print(f"[career-fields] 对账 {checked} 条；源文本带职业字段标签 {with_labels} 处")


class TestFieldLabelsAreStable:
    def test_labels_match_schema_detect_aliases(self):
        """标签必须与 `schema_detect.EXTRA_COLUMN_ALIASES` 的源列名一致。

        不一致 = 解析器找不到标签 → 回填静默变成 0 处。用断言把这两个地方钉在一起。
        """
        from app.core.job_agent.tools.schema_detect import EXTRA_COLUMN_ALIASES

        aliases = set(EXTRA_COLUMN_ALIASES)
        for label in FIELD_LABELS.values():
            assert label in aliases, f"标签 {label!r} 不在 EXTRA_COLUMN_ALIASES 里"
