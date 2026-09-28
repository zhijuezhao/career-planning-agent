"""token 计量与 LLM 预算闸门。

这两件事是"省 token"这个硬要求的执行机构：计量不准则预算形同虚设，
预算不执行则一次误上传就能按"有多少个域名"花掉任意额度。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.link_enrich.budget import LlmBudget
from app.core.llm.usage import EMPTY_USAGE, TokenUsage, extract_usage, usage_or_warn


class TestExtractUsage:
    def test_reads_langchain_usage_metadata(self):
        # 实测的 longcat/deepseek 形状
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 9, "output_tokens": 1, "total_tokens": 10}
        )
        assert extract_usage(message) == TokenUsage(9, 1, 10)

    def test_reads_response_metadata_token_usage_fallback(self):
        # 部分适配器把用量放在 response_metadata["token_usage"]（本仓实测是缺的，
        # 所以两条路都要认）
        message = SimpleNamespace(
            usage_metadata=None,
            response_metadata={"token_usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        )
        usage = extract_usage(message)
        assert usage.input_tokens == 5 and usage.output_tokens == 2
        assert usage.total_tokens == 7  # total 缺失时按 in+out 兜底

    def test_object_shaped_usage_metadata(self):
        # pydantic 模型不是 dict，要能用属性读
        message = SimpleNamespace(usage_metadata=SimpleNamespace(input_tokens=3, output_tokens=4))
        assert extract_usage(message).total_tokens == 7

    def test_string_numbers_are_accepted(self):
        message = SimpleNamespace(usage_metadata={"input_tokens": "12", "total_tokens": "20"})
        usage = extract_usage(message)
        assert usage.input_tokens == 12 and usage.total_tokens == 20

    def test_missing_usage_is_zero_not_an_error(self):
        for message in (None, SimpleNamespace(), SimpleNamespace(usage_metadata=None)):
            assert extract_usage(message) == EMPTY_USAGE

    def test_garbage_usage_does_not_raise(self):
        message = SimpleNamespace(usage_metadata={"input_tokens": object(), "total_tokens": "abc"})
        assert extract_usage(message).total_tokens == 0

    def test_usage_or_warn_still_returns_zeros(self):
        assert usage_or_warn(SimpleNamespace(), function_key="job_link_extract") == EMPTY_USAGE

    def test_token_usage_is_additive(self):
        assert (TokenUsage(1, 2, 3) + TokenUsage(10, 20, 30)) == TokenUsage(11, 22, 33)


class TestLlmBudget:
    def test_counts_calls_and_tokens(self):
        budget = LlmBudget(max_calls=3, max_tokens=1000)
        assert budget.can_call()
        budget.spend(TokenUsage(10, 5, 15))
        assert budget.calls == 1 and budget.usage.total_tokens == 15
        assert not budget.exhausted

    def test_call_limit_stops_further_calls(self):
        budget = LlmBudget(max_calls=2)
        budget.spend(TokenUsage(1, 1, 2))
        budget.spend(TokenUsage(1, 1, 2))
        assert budget.exhausted
        assert not budget.can_call()
        assert budget.blocked

    def test_token_limit_stops_further_calls(self):
        budget = LlmBudget(max_calls=100, max_tokens=50)
        budget.spend(TokenUsage(40, 20, 60))
        assert budget.exhausted
        assert not budget.can_call()

    def test_zero_or_negative_means_unlimited(self):
        # 一条规则，不要两种解释：0 = 不限制；要关掉 LLM 层请用 LINK_ENRICH_LLM_ENABLED
        for budget in (LlmBudget(max_calls=0, max_tokens=0), LlmBudget(max_calls=-1, max_tokens=-1)):
            for _ in range(50):
                budget.spend(TokenUsage(1000, 1000, 2000))
            assert budget.can_call()
            assert not budget.exhausted

    def test_missing_usage_still_burns_a_call(self):
        # 否则"供应商不回报用量"就绕过了调用数闸门
        budget = LlmBudget(max_calls=1)
        budget.spend(None)
        assert budget.calls == 1
        assert not budget.can_call()

    def test_as_stats_shape(self):
        budget = LlmBudget(max_calls=5, max_tokens=100)
        budget.spend(TokenUsage(7, 3, 10))
        assert budget.as_stats() == {
            "llm_calls": 1,
            "tokens_used": 10,
            "tokens_input": 7,
            "tokens_output": 3,
            "budget_exceeded": False,
        }
