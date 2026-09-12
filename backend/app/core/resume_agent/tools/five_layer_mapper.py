from __future__ import annotations

from langchain_core.tools import tool

from app.core.resume_agent.schemas import ParsedResume


def map_to_five_layers(parsed: ParsedResume) -> dict:
    return {
        "intention": parsed.intention.model_dump(),
        "traits": parsed.traits.model_dump(),
        "practice": parsed.practice.model_dump(),
        "soft_skills": parsed.soft_skills.model_dump(),
        "hard_skills": parsed.hard_skills.model_dump(),
    }


@tool
def five_layer_mapper(parsed_resume_dict: dict) -> dict:
    """Map a ParsedResume dict into the five-layer ability portrait structure.

    Args:
        parsed_resume_dict: Dict representation of ParsedResume (from resume_parser).

    Returns:
        Dict with keys: intention, traits, practice, soft_skills, hard_skills.
    """
    parsed = ParsedResume.model_validate(parsed_resume_dict)
    return map_to_five_layers(parsed)
