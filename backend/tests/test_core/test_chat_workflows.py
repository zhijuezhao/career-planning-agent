"""C1 的确定型工作流（``app/core/chat/workflows.py``）—— 连 dev DB，**只读**。

两件事要守住：
1. **归类不漏**：库里每一条真实岗位名都要能被归类，否则「其他」会变成黑洞；
2. **产出的 viz 合法**：形状不对前端就渲染不了（``is_valid_viz`` 是最后一道闸）。
"""

from __future__ import annotations

import asyncio

import pytest
from app.core.chat.viz import is_valid_viz
from app.core.chat.workflows import (
    MAX_LIST_LIMIT,
    OTHER_CATEGORY,
    WorkflowContext,
    classify_title,
    job_catalog,
)
from app.domain.models.job import JobProfile, JobRawData
from sqlalchemy import func, select
from tests.conftest import test_session_factory


class TestClassifyTitle:
    def test_keyword_priority_regressions(self):
        """钉死注释里写明的三条优先级（它们都是真实踩点，不是假想）。"""
        # ① JavaScript 不能被「后端/语言」的 Java 抢走
        assert classify_title("JavaScript") == "前端 / 客户端 / 游戏"
        assert classify_title("Java") == "后端 / 语言"
        # ② 游戏测试 / 测试经理 属于测试
        assert classify_title("游戏测试") == "测试"
        assert classify_title("测试经理") == "测试"
        # ③ 语音/视频/图形开发 是媒体开发，不能因为含「语音」落进算法
        assert classify_title("语音/视频/图形开发") == "前端 / 客户端 / 游戏"
        assert classify_title("语音算法") == "算法 / AI"

    def test_support_roles_split_correctly(self):
        assert classify_title("IT技术支持") == "运维 / 网络 / 安全 / 支持"
        assert classify_title("售后技术支持") == "售前 / 客户"
        assert classify_title("技术文档工程师") == "文档"
        assert classify_title("技术总监") == "高管 / 架构"

    def test_unknown_and_empty(self):
        assert classify_title("") == OTHER_CATEGORY
        assert classify_title("完全不认识的名字") == OTHER_CATEGORY

    def test_every_real_title_is_classified(self):
        """**导入进来的**每一条岗位名都必须归类成功。

        这个断言会跟着数据走：用户以后导入新岗位时，如果有名字归不进任何类，
        这里会红 —— 那是提醒"该给 ``TITLE_CATEGORIES`` 加关键词了"，而不是代码坏了。

        ⚠️ 只看"有同名 `job_raw_data` 行"的岗位（= 真导入数据）：测试自己 upsert 出来的
        岗位（`b22_*` 之类）没有原始行，不该被这条断言波及。
        """

        async def _titles() -> list[str]:
            async with test_session_factory() as session:
                raw_titles = set(
                    (await session.execute(select(JobRawData.title))).scalars().all()
                )
                profile_titles = list(
                    (await session.execute(select(JobProfile.title))).scalars().all()
                )
                return [t for t in profile_titles if t in raw_titles]

        titles = asyncio.run(_titles())
        if not titles:
            pytest.skip("库里没有可追溯的导入岗位")

        unclassified = [t for t in titles if classify_title(t) == OTHER_CATEGORY]
        assert unclassified == [], f"这些岗位名没被归类：{unclassified}"


class TestJobCatalog:
    @staticmethod
    def _run(params: dict) -> tuple[object, int]:
        """跑工作流，同时把库里的岗位总数带回来（用于对账）。"""

        async def _call():
            async with test_session_factory() as session:
                result = await job_catalog(session, WorkflowContext(params=params, user_id=0))
                total = (
                    await session.execute(select(func.count()).select_from(JobProfile))
                ).scalar() or 0
                return result, total

        return asyncio.run(_call())

    def test_list_mode_returns_table_viz(self):
        result, total = self._run({"mode": "list"})
        assert isinstance(result.text, str) and result.text
        assert len(result.viz) == 1
        viz = result.viz[0]
        assert is_valid_viz(viz)
        assert viz["kind"] == "table"
        assert viz["columns"] == ["#", "岗位名称"]
        assert len(viz["rows"]) == min(total, 50)

    def test_list_limit_is_clamped_for_dirty_input(self):
        """脏输入不许抛错；条数必须夹在 1..MAX_LIST_LIMIT。"""
        assert len(self._run({"mode": "list", "limit": "abc"})[0].viz[0]["rows"]) >= 1
        assert len(self._run({"mode": "list", "limit": -5})[0].viz[0]["rows"]) == 1
        huge, _ = self._run({"mode": "list", "limit": 10**9})
        assert len(huge.viz[0]["rows"]) <= MAX_LIST_LIMIT

    def test_distribution_mode_returns_bar_viz(self):
        result, total = self._run({"mode": "distribution"})
        assert len(result.viz) == 1
        viz = result.viz[0]
        assert is_valid_viz(viz)
        assert viz["kind"] == "bar"
        series = viz["option"]["series"][0]
        assert series["type"] == "bar"
        # 各段之和必须等于库里的岗位总数（分类是"划分"，不是"筛选"）
        assert sum(series["data"]) == total
        assert len(viz["option"]["xAxis"]["data"]) == len(series["data"])

    def test_empty_db_returns_text_without_viz(self):
        """空库不许编数据：给一句实话，不发图。"""

        async def _call():
            session = _EmptyResultSession()
            return await job_catalog(session, WorkflowContext(params={"mode": "list"}, user_id=0))

        result = asyncio.run(_call())
        assert "还没有岗位" in result.text
        assert result.viz == []


class _EmptyResultSession:
    """只为"空库"这一条路径造的最小假 session（真库现在有 82 条，替不掉）。"""

    class _Scalar:
        def scalar(self):
            return 0

    async def execute(self, *args, **kwargs):
        return self._Scalar()
