from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger


class JobImportState(TypedDict, total=False):
    """State for the job import pipeline.

    All fields are optional (total=False) so nodes can incrementally
    populate the state as the pipeline progresses.
    """
    # Input
    file_path: str
    sheet_name: str | int
    nrows: int | None

    # Stage 1: Load
    raw_rows: list[dict]

    # Stage 2: Clean
    cleaned_rows: list[dict]

    # Stage 3: Dedup
    deduped_rows: list[dict]

    # Stage 4: Quality Judge
    quality_results: list[dict]
    passed_rows: list[dict]       # A/B/C grade rows
    rejected_rows: list[dict]     # D grade rows

    # Stage 5: Extract
    extracted_rows: list[dict]

    # Stage 6: Portrait
    portrait_rows: list[dict]

    # Output
    total_input: int
    total_passed: int
    total_rejected: int
    total_exported: int

    # Control
    status: str
    error_message: str | None


async def node_load_data(state: JobImportState) -> dict:
    from app.core.job_agent.tools.data_loader import load_excel_data

    result = await load_excel_data.ainvoke({
        "file_path": state["file_path"],
        "sheet_name": state.get("sheet_name", 0),
        "nrows": state.get("nrows"),
    })

    # S7-3 修复：读取失败必须显式冒泡。
    # `load_excel_data` 失败时返回 {"total": 0, "rows": [], "error": "..."}，
    # 原先只取 rows → 损坏/不可读的文件会被当成「空表」一路跑完并报 completed，
    # 调用方看不到任何原因（实测：64 字节垃圾 .xlsx 被判 completed）。
    if result.get("error"):
        logger.error("Import: data load failed | error={}", result["error"])
        return {
            "raw_rows": [],
            "total_input": 0,
            "status": "failed",
            "error_message": str(result["error"]),
        }

    raw_rows = result.get("rows", [])
    logger.info("Import: data loaded | rows={}", len(raw_rows))
    return {
        "raw_rows": raw_rows,
        "total_input": len(raw_rows),
        "status": "loaded",
    }


async def node_clean_data(state: JobImportState) -> dict:
    from app.core.job_agent.tools.pre_cleaner import clean_job_data

    result = await clean_job_data.ainvoke({"rows": state["raw_rows"]})
    cleaned = result.get("cleaned_rows", [])
    logger.info("Import: data cleaned | rows={}", len(cleaned))
    return {"cleaned_rows": cleaned, "status": "cleaned"}


async def node_dedup(state: JobImportState) -> dict:
    from app.core.job_agent.tools.dedup import deduplicate_jobs

    result = await deduplicate_jobs.ainvoke({"rows": state["cleaned_rows"]})
    deduped = result.get("deduped_rows", [])
    logger.info(
        "Import: dedup completed | exact={} fuzzy={} remaining={}",
        result.get("exact_dedup_count", 0),
        result.get("fuzzy_dedup_count", 0),
        len(deduped),
    )
    return {"deduped_rows": deduped, "status": "deduped"}


async def node_quality_judge(state: JobImportState) -> dict:
    import json

    from app.core.job_agent.tools.quality_judge import quality_judge

    passed: list[dict] = []
    rejected: list[dict] = []
    results: list[dict] = []

    for row in state["deduped_rows"]:
        job_data_str = json.dumps(row, ensure_ascii=False)
        judge_result = await quality_judge.ainvoke({"job_data": job_data_str})
        results.append(judge_result)

        if judge_result.get("grade") == "D":
            rejected.append(row)
        else:
            passed.append(row)

    logger.info(
        "Import: quality judged | passed={} rejected={}",
        len(passed), len(rejected),
    )
    return {
        "quality_results": results,
        "passed_rows": passed,
        "rejected_rows": rejected,
        "total_passed": len(passed),
        "total_rejected": len(rejected),
        "status": "judged",
    }


async def node_extract(state: JobImportState) -> dict:
    from app.core.job_agent.tools.job_extractor import job_extractor

    extracted: list[dict] = []
    for row in state["passed_rows"]:
        job_text = _row_to_text(row)
        extract_result = await job_extractor.ainvoke({"job_text": job_text})
        extracted.append(extract_result)

    logger.info("Import: extraction completed | rows={}", len(extracted))
    return {"extracted_rows": extracted, "status": "extracted"}


async def node_portrait(state: JobImportState) -> dict:
    import json

    from app.core.job_agent.tools.portrait_builder import portrait_builder

    portraits: list[dict] = []
    for row in state["passed_rows"]:
        job_data_str = json.dumps(row, ensure_ascii=False)
        portrait_result = await portrait_builder.ainvoke({"job_data": job_data_str})
        portraits.append(portrait_result)

    logger.info("Import: portraits generated | rows={}", len(portraits))
    return {
        "portrait_rows": portraits,
        "total_exported": len(portraits),
        "status": "completed",
    }


def _row_to_text(row: dict) -> str:
    """Convert a job data row to a plain-text representation for extraction."""
    parts = []
    for key in ("title", "company", "city", "salary", "industry", "description", "requirements"):
        val = row.get(key)
        if val:
            parts.append(f"{key}: {val}")
    return "\n".join(parts)


def build_import_pipeline() -> StateGraph:
    graph = StateGraph(JobImportState)

    graph.add_node("load_data", node_load_data)
    graph.add_node("clean_data", node_clean_data)
    graph.add_node("dedup", node_dedup)
    graph.add_node("quality_judge", node_quality_judge)
    graph.add_node("extract", node_extract)
    graph.add_node("portrait", node_portrait)

    graph.set_entry_point("load_data")
    graph.add_edge("load_data", "clean_data")
    graph.add_edge("clean_data", "dedup")
    graph.add_edge("dedup", "quality_judge")
    graph.add_edge("quality_judge", "extract")
    graph.add_edge("extract", "portrait")
    graph.add_edge("portrait", END)

    return graph


def compile_import_pipeline():
    return build_import_pipeline().compile()
