from langchain_core.tools import BaseTool

from app.config import get_settings
from app.core.agent.tools.jobs import job_detail, job_search
from app.core.agent.tools.knowledge import career_knowledge_search
from app.core.agent.tools.link_fetch import link_fetch
from app.core.agent.tools.matching import gap_analysis, job_compare
from app.core.agent.tools.report_tool import generate_career_report
from app.core.agent.tools.safety import content_safety_check
from app.core.agent.tools.search import web_search
from app.core.agent.tools.snapshot import user_snapshot

__all__ = [
    "AGENT_TOOLS",
    "career_knowledge_search",
    "content_safety_check",
    "gap_analysis",
    "generate_career_report",
    "get_agent_tools",
    "job_compare",
    "job_detail",
    "job_search",
    "link_fetch",
    "user_snapshot",
    "web_search",
]

#: 全部已实现的 agent 工具（**是否暴露给模型**由 `get_agent_tools()` 决定）
AGENT_TOOLS: list[BaseTool] = [
    # C2（P4）：**零 LLM 成本**的只读工具 —— 查库就能答的问题不必让模型"回忆"
    job_search,
    job_detail,
    user_snapshot,
    # C3（P5）：六维对比 —— 会产 radar viz（工具产图链路见 nodes._split_tool_viz）
    gap_analysis,
    job_compare,
    # C4（P6）：抓招聘链接并抽字段。**服务端出网**，所以走 link_enrich 的 SSRF 守卫
    link_fetch,
    career_knowledge_search,
    content_safety_check,
    web_search,
    generate_career_report,
]


def get_agent_tools() -> list[BaseTool]:
    """当前配置下真正可用给模型的工具集（chat 调用点用这个，而不是 `AGENT_TOOLS`）。

    `web_search` 依赖 `TAVILY_API_KEY`：**没配就不暴露** —— 否则模型可能反复调用一个
    必然报错的工具，在 ReAct 循环里白耗轮次与 token。
    """
    if get_settings().tavily_api_key:
        return list(AGENT_TOOLS)
    return [t for t in AGENT_TOOLS if t.name != "web_search"]
