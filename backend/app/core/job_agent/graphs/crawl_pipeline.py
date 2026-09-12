from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger


class CrawlState(TypedDict, total=False):
    """State for the web crawl and industry report pipeline.

    All fields are optional (total=False) so nodes can incrementally
    populate the state.
    """
    # Input
    keywords: str
    industry: str | None
    max_results: int

    # Stage 1: Search
    search_results: list[dict]
    search_source: str

    # Stage 2: Report
    report_text: str
    report_sections: dict[str, str]

    # Control
    status: str
    error_message: str | None


async def node_search(state: CrawlState) -> dict:
    """Search the web for industry/job data."""
    from app.core.job_agent.tools.web_collector import web_collector

    result = await web_collector.ainvoke({
        "keywords": state["keywords"],
        "max_results": state.get("max_results", 10),
    })
    logger.info("Crawl: search complete | keywords={!r:.60} | results={} | source={}",
                state["keywords"], result["total"], result["source"])
    return {
        "search_results": result.get("results", []),
        "search_source": result.get("source", "none"),
        "status": "searched",
    }


async def node_enrich(state: CrawlState) -> dict:
    """Enrich search results by fetching content from top URLs.

    Uses url_fetcher to get page content for the top results to
    provide richer context for report generation.
    """
    from app.core.job_agent.tools.url_fetcher import url_fetcher
    from app.core.job_agent.tools.url_safety import url_safety_check

    results = state.get("search_results", [])
    enriched = list(results)  # Start with original results

    # Attempt to fetch content for top 3 results
    for i, r in enumerate(results[:3]):
        url = r.get("url", "")
        if not url:
            continue

        # Safety check first
        safety = await url_safety_check.ainvoke({
            "url": url,
            "check_reachability": True,
        })
        if not safety.get("is_safe", False):
            logger.info("Crawl: skipping unsafe URL | url={}", url)
            continue

        # Fetch content
        fetch_result = await url_fetcher.ainvoke({"url": url, "timeout": 15.0})
        if fetch_result.get("success"):
            enriched[i]["full_content"] = fetch_result["content"]
            enriched[i]["page_title"] = fetch_result["title"]
            enriched[i]["is_ai_enriched"] = False
        else:
            # Mark as AI-enriched candidate (LLM will generate summary)
            enriched[i]["full_content"] = ""
            enriched[i]["is_ai_enriched"] = True

    logger.info("Crawl: enrichment complete | enriched={}", len(results))
    return {"search_results": enriched, "status": "enriched"}


async def node_report(state: CrawlState) -> dict:
    """Generate an industry report from collected data."""
    from app.core.job_agent.tools.report_summarizer import report_summarizer

    # Build a summarised view of the search results for the LLM
    collected = _build_collected_data(state.get("search_results", []))
    data_str = json.dumps(collected, ensure_ascii=False, indent=2)

    result = await report_summarizer.ainvoke({
        "data": data_str,
        "industry": state.get("industry"),
    })

    logger.info("Crawl: report generated | industry={!r:.40} | chars={}",
                state.get("industry"), len(result.get("summary", "")))
    return {
        "report_text": result.get("summary", ""),
        "report_sections": result.get("sections", {}),
        "status": "completed",
    }


def _build_collected_data(results: list[dict]) -> list[dict]:
    """Build a summarised view of search results for the LLM."""
    collected = []
    for r in results:
        entry = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "source": r.get("source", ""),
        }
        full = r.get("full_content", "")
        if full:
            entry["full_content"] = full[:2000]  # Truncate to avoid token limits
        collected.append(entry)
    return collected


def build_crawl_pipeline() -> StateGraph:
    graph = StateGraph(CrawlState)

    graph.add_node("search", node_search)
    graph.add_node("enrich", node_enrich)
    graph.add_node("report", node_report)

    graph.set_entry_point("search")
    graph.add_edge("search", "enrich")
    graph.add_edge("enrich", "report")
    graph.add_edge("report", END)

    return graph


def compile_crawl_pipeline():
    return build_crawl_pipeline().compile()
