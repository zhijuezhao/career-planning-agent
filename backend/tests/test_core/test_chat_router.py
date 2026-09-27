"""C1 的 L1 意图路由（``app/core/chat/router.py``）—— **纯函数，不连库**。

这个文件的价值不只是"规则能命中"，更是**把规则的窄边界钉死**：
``现在有哪些前端岗位`` 必须**不**命中 —— 否则 L1 会抢走本该交给 agent 的"带过滤条件"
问题，而用规则硬解析"前端"是 P4/C2 做 ``job_search`` 时才该干的事。
"""

from __future__ import annotations

import re

import pytest
from app.core.chat.router import L1_RULES, route
from app.core.chat.workflows import WORKFLOWS


class TestL1Hits:
    @pytest.mark.parametrize(
        "message",
        [
            "有哪些岗位",
            "现在有哪些岗位？",
            "有多少岗位",
            "一共有多少个岗位",
            "岗位列表",
            "列出岗位",
            "给我全部岗位",
        ],
    )
    def test_catalog_list(self, message: str):
        decision = route(message)
        assert decision.layer == "L1"
        assert decision.workflow == "job_catalog"
        assert decision.params["mode"] == "list"
        assert decision.is_workflow

    @pytest.mark.parametrize(
        "message",
        ["岗位分布", "有哪些方向", "岗位大类分布", "岗位类别统计"],
    )
    def test_catalog_distribution(self, message: str):
        decision = route(message)
        assert decision.layer == "L1"
        assert decision.workflow == "job_catalog"
        assert decision.params["mode"] == "distribution"

    @pytest.mark.parametrize(
        ("message", "expected_limit"),
        [("前20个岗位", 20), ("列出前 30 个岗位", 30), ("给我前5个岗位", 5)],
    )
    def test_limit_entity_extraction(self, message: str, expected_limit: int):
        """实体抽取：把「前 N 个岗位」里的 N 抽成工作流入参。"""
        decision = route(message)
        assert decision.layer == "L1"
        assert decision.params == {"mode": "list", "limit": expected_limit}


class TestL1Misses:
    """**故意不命中**的问法 —— 这些继续走 agent，行为与 C1 之前逐字一致。"""

    @pytest.mark.parametrize(
        "message",
        [
            # 带过滤条件：需要真正的 job_search（P4/C2），规则不该硬解析
            "现在有哪些前端岗位",
            "有哪些适合我的岗位",
            "北京有哪些算法岗位",
            # 与岗位目录无关
            "你好",
            "帮我看看我的简历",
            "我该怎么准备面试",
            "岗位",
        ],
    )
    def test_goes_to_agent(self, message: str):
        decision = route(message)
        assert decision.layer == "L3"
        assert decision.workflow is None
        assert not decision.is_workflow
        assert decision.params == {}

    @pytest.mark.parametrize("message", ["", "   ", None])
    def test_empty_message_is_l3(self, message):
        decision = route(message)  # type: ignore[arg-type]
        assert decision.layer == "L3"
        assert decision.workflow is None


class TestRuleTableIntegrity:
    def test_every_rule_points_to_a_registered_workflow(self):
        """规则里写错工作流名 = 运行期 KeyError → 这里直接拦住。"""
        for rule in L1_RULES:
            assert rule.workflow in WORKFLOWS, f"{rule.name} 指向未注册的工作流 {rule.workflow!r}"

    @pytest.mark.parametrize("rule", L1_RULES, ids=lambda r: r.name)
    def test_patterns_compile(self, rule):
        for pattern in rule.patterns:
            re.compile(pattern)

    def test_rule_names_are_unique(self):
        names = [rule.name for rule in L1_RULES]
        assert len(names) == len(set(names))

    def test_rule_order_puts_specific_first(self):
        """顺序即优先级：``job_catalog.list.limit`` 必须排在 ``job_catalog.list`` 前，
        否则「列出前 20 个岗位」会被泛规则抢走、丢参数。"""
        names = [rule.name for rule in L1_RULES]
        assert names.index("job_catalog.list.limit") < names.index("job_catalog.list")
