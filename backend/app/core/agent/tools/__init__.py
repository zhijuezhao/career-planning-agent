from app.core.agent.tools.knowledge import career_knowledge_search
from app.core.agent.tools.report_tool import generate_career_report
from app.core.agent.tools.safety import content_safety_check
from app.core.agent.tools.search import web_search

__all__ = [
    "career_knowledge_search",
    "content_safety_check",
    "web_search",
    "generate_career_report",
]

AGENT_TOOLS = [
    career_knowledge_search,
    content_safety_check,
    web_search,
    generate_career_report,
]