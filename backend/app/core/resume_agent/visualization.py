from __future__ import annotations

from app.core.resume_agent.schemas import TOP_DIMENSIONS


def build_radar_option(dimension_scoring: dict | None) -> dict:
    indicators = [{"name": dim, "max": 5} for dim in TOP_DIMENSIONS]

    if dimension_scoring is None:
        return {
            "indicators": indicators,
            "values": [0] * len(TOP_DIMENSIONS),
            "total_score": 0,
        }

    dimensions = dimension_scoring.get("dimensions", {})
    values = []
    for dim in TOP_DIMENSIONS:
        dim_data = dimensions.get(dim, {})
        values.append(dim_data.get("score", 0))

    return {
        "indicators": indicators,
        "values": values,
        "total_score": dimension_scoring.get("total_dim_score", 0),
    }
