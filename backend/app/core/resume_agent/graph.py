from __future__ import annotations

from langgraph.graph import END, StateGraph
from loguru import logger

from app.core.resume_agent.state import ResumeState


async def node_extract_pdf(state: ResumeState) -> dict:
    from app.core.resume_agent.tools.pdf_text_extractor import _extract_pdf_text

    result = _extract_pdf_text(state["file_path"])
    logger.info("PDF extracted | resume_id={} | pages={}", state["resume_id"], result["page_count"])
    return {
        "raw_text": result["raw_text"],
        "page_count": result["page_count"],
        "truncated": result["truncated"],
        "status": "parsing",
    }


async def node_parse_resume(state: ResumeState) -> dict:
    from app.core.resume_agent.tools.resume_parser import _parse_resume

    parsed = await _parse_resume(state["raw_text"])
    logger.info("Resume parsed | resume_id={}", state["resume_id"])
    return {
        "parsed_resume": parsed,
        "basic_info": parsed.get("basic_info", {}),
        "dimension_scoring": parsed.get("dimension_scoring"),
        "status": "parsed",
    }


async def node_map_layers(state: ResumeState) -> dict:
    from app.core.resume_agent.schemas import ParsedResume
    from app.core.resume_agent.tools.five_layer_mapper import map_to_five_layers

    parsed = ParsedResume.model_validate(state["parsed_resume"])
    layers = map_to_five_layers(parsed)
    logger.info("Five layers mapped | resume_id={}", state["resume_id"])
    return {"five_layers": layers}


async def node_write_scores(state: ResumeState) -> dict:
    scoring = state.get("dimension_scoring")
    if scoring is None:
        logger.warning("No dimension_scoring, skipping score write | resume_id={}", state["resume_id"])
        return {"status": "parsed"}

    profile_id = state.get("profile_id")
    if profile_id is None:
        logger.warning("No profile_id yet, skipping score write | resume_id={}", state["resume_id"])
        return {"status": "parsed"}

    from app.core.resume_agent.schemas import DimensionScoring
    from app.core.resume_agent.tools.score_deriver import write_dimension_scores
    from app.infrastructure.database import async_session_factory

    validated = DimensionScoring.model_validate(scoring)
    async with async_session_factory() as session:
        try:
            rows = await write_dimension_scores("candidate", profile_id, validated, session)
            await session.commit()
            logger.info("Scores written | resume_id={} | rows={}", state["resume_id"], rows)
        except Exception:
            await session.rollback()
            raise

    return {"status": "scoring"}


async def node_embed_profile(state: ResumeState) -> dict:
    from app.core.llm.embeddings import get_embeddings
    from app.core.resume_agent.embedding_text import build_portrait_text

    content = build_portrait_text(state["five_layers"])
    if not content.strip():
        logger.warning("Empty portrait text, skipping embedding | resume_id={}", state["resume_id"])
        return {"embedding_content": content, "embedding": None, "status": "embedding"}

    try:
        embeddings = get_embeddings()
        vector = await embeddings.aembed_query(content)
        logger.info("Embedding generated | resume_id={} | dims={}", state["resume_id"], len(vector))
        return {"embedding_content": content, "embedding": vector, "status": "embedding"}
    except Exception as exc:
        logger.warning("Embedding failed | resume_id={} | error={}", state["resume_id"], exc)
        return {"embedding_content": content, "embedding": None, "status": "embedding"}


async def node_generate_report(state: ResumeState) -> dict:
    from app.core.resume_agent.tools.report_builder import _build_report

    report_text = await _build_report(
        five_layers=state["five_layers"],
        dimension_scoring=state.get("dimension_scoring"),
        basic_info=state.get("basic_info", {}),
    )
    logger.info("Report generated | resume_id={}", state["resume_id"])
    return {"report_text": report_text, "status": "reporting"}


async def node_persist(state: ResumeState) -> dict:
    from app.domain.services.resume_service import (
        save_career_report,
        save_user_match_embedding,
        update_resume_status,
        upsert_ability_profile,
    )
    from app.infrastructure.database import async_session_factory

    async with async_session_factory() as session:
        try:
            profile = await upsert_ability_profile(
                session, state["user_id"], state["five_layers"]
            )
            profile_id = profile.id

            await save_user_match_embedding(
                session, state["user_id"], profile_id,
                state.get("embedding_content", ""),
                state.get("embedding"),
            )

            await save_career_report(
                session, state["user_id"], profile_id,
                state["report_text"],
                target_job=(state.get("basic_info") or {}).get("target_position"),
            )

            await update_resume_status(
                session, state["resume_id"], status="done",
                profile_id=profile_id,
                parsed_data=state.get("parsed_resume"),
                raw_text=state.get("raw_text"),
                page_count=state.get("page_count"),
            )

            await session.commit()
            logger.info("Pipeline persisted | resume_id={} | profile_id={}", state["resume_id"], profile_id)
            return {"profile_id": profile_id, "status": "done"}
        except Exception:
            await session.rollback()
            raise


def _should_continue(state: ResumeState) -> str:
    if state.get("error_message"):
        return "error"
    return "continue"


def build_resume_graph() -> StateGraph:
    graph = StateGraph(ResumeState)

    graph.add_node("extract_pdf", node_extract_pdf)
    graph.add_node("parse_resume", node_parse_resume)
    graph.add_node("map_layers", node_map_layers)
    graph.add_node("write_scores", node_write_scores)
    graph.add_node("embed_profile", node_embed_profile)
    graph.add_node("generate_report", node_generate_report)
    graph.add_node("persist", node_persist)

    graph.set_entry_point("extract_pdf")
    graph.add_edge("extract_pdf", "parse_resume")
    graph.add_edge("parse_resume", "map_layers")
    graph.add_edge("map_layers", "write_scores")
    graph.add_edge("write_scores", "embed_profile")
    graph.add_edge("embed_profile", "generate_report")
    graph.add_edge("generate_report", "persist")
    graph.add_edge("persist", END)

    return graph


def compile_resume_graph():
    return build_resume_graph().compile()
