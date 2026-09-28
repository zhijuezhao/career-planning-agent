"""C4 工具 `link_fetch`：形状、正文裁剪、安全拦截的可读回执、注册表。

出网部分在 `test_link_enrich_service.py` 里用 MockTransport 覆盖；这里只钉**工具契约**
—— 因为模型看到的就是这个形状，字段改名或忘了截断都会直接反映成"模型把整页正文
倒进上下文"，而那种问题在功能测试里看不出来。
"""

from __future__ import annotations

import importlib

from app.core.agent.tools import AGENT_TOOLS, get_agent_tools
from app.core.agent.tools.link_fetch import DEFAULT_RETURN_CHARS, link_fetch

# ⚠️ 必须用 importlib 取**模块**：`from app.core.agent.tools import link_fetch`
# 拿到的是同名**工具对象**（包 `__init__` 把 `link_fetch` 这个名字导出成了 StructuredTool），
# 对它 monkeypatch 会报 "StructuredTool has no attribute 'fetch_one'"。
module = importlib.import_module("app.core.agent.tools.link_fetch")

_LONG_TEXT = "岗位描述" * 2000


class TestRegistration:
    def test_tool_is_registered_and_exposed(self):
        names = {t.name for t in AGENT_TOOLS}
        assert "link_fetch" in names
        # link_fetch 不依赖任何可选 key，所以必须始终对模型可见
        assert "link_fetch" in {t.name for t in get_agent_tools()}

    def test_tool_description_mentions_url(self):
        assert "url" in (link_fetch.description or "").lower()


class TestSuccessShape:
    async def test_returns_fields_and_clipped_text(self, monkeypatch):
        async def fake_fetch_one(url, **kwargs):
            return {
                "url": url,
                "domain": "jobs.example.com",
                "success": True,
                "from_cache": False,
                "status_code": 200,
                "tiers_hit": ["jsonld", "text"],
                "fields": {"title": "Java 工程师", "company": "示例科技"},
                "text": _LONG_TEXT,
                "truncated": False,
                "error": None,
                "blocked_reason": None,
            }

        monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
        result = await link_fetch.ainvoke({"url": "https://jobs.example.com/1", "max_chars": 50})

        assert result["success"] is True
        assert result["fields"]["company"] == "示例科技"
        # 正文必须按 max_chars 裁掉：不裁的话一次工具调用就能吃掉大半个上下文
        assert len(result["text"]) == 50
        assert result["text_chars"] == len(_LONG_TEXT)
        assert result["text_truncated"] is True

    async def test_default_clip_is_the_module_constant(self, monkeypatch):
        async def fake_fetch_one(url, **kwargs):
            return {
                "url": url, "domain": "a.com", "success": True, "from_cache": False,
                "status_code": 200, "tiers_hit": [], "fields": {}, "text": _LONG_TEXT,
                "truncated": True, "error": None, "blocked_reason": None,
            }

        monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
        result = await link_fetch.ainvoke({"url": "https://a.com/1"})
        assert len(result["text"]) == DEFAULT_RETURN_CHARS

    async def test_short_text_is_not_marked_truncated(self, monkeypatch):
        async def fake_fetch_one(url, **kwargs):
            return {
                "url": url, "domain": "a.com", "success": True, "from_cache": False,
                "status_code": 200, "tiers_hit": ["og"], "fields": {"title": "t"},
                "text": "很短", "truncated": False, "error": None, "blocked_reason": None,
            }

        monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
        result = await link_fetch.ainvoke({"url": "https://a.com/1"})
        assert result["text"] == "很短"
        assert result["text_truncated"] is False


class TestBlockedReceipt:
    async def test_blocked_url_reports_a_readable_reason(self, monkeypatch):
        """被守卫拦下时必须把原因回给模型。

        只说 "失败" 的话，模型会换个写法继续试同一个内网地址（在 ReAct 里白耗轮次）；
        说清"这是安全策略拒绝"它才会改道。
        """

        async def fake_fetch_one(url, **kwargs):
            return {
                "url": url, "domain": "", "success": False, "from_cache": False,
                "status_code": None, "tiers_hit": [], "fields": {}, "text": "",
                "truncated": False, "error": "安全校验未通过：链路本地地址",
                "blocked_reason": "链路本地地址（含云元数据 169.254.169.254）",
            }

        monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
        result = await link_fetch.ainvoke({"url": "http://169.254.169.254/latest/meta-data/"})

        assert result["success"] is False
        assert result.get("blocked") is True
        assert "安全策略拒绝" in result["error"]


class TestErrorHandling:
    async def test_internal_exception_becomes_a_result_not_a_raise(self, monkeypatch):
        """工具绝不能把异常抛进 ReAct 循环 —— 那会直接中断整轮对话。"""

        async def boom(url, **kwargs):
            raise RuntimeError("数据库连接断了")

        monkeypatch.setattr(module, "fetch_one", boom)
        result = await link_fetch.ainvoke({"url": "https://a.com/1"})

        assert result["success"] is False
        assert "抓取失败" in result["error"]
        assert "数据库连接断了" in result["error"]
