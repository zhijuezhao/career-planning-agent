from app.core.resume_agent.schemas import TOP_DIMENSIONS
from app.core.resume_agent.visualization import build_radar_option


def test_build_radar_option_with_scoring():
    scoring = {
        "profile_type": "candidate",
        "total_dim_score": 3.5,
        "dimensions": {
            "专业技术能力": {"score": 4.0, "sub_dimensions": {"核心专业技能": 4.0, "工具与技术栈": 4.0}},
            "实践经验背景": {"score": 3.0, "sub_dimensions": {"相关经历匹配度": 3.0, "实践深度与产出": 3.0}},
            "通用软素质": {"score": 3.5, "sub_dimensions": {}},
            "职业匹配度": {"score": 3.5, "sub_dimensions": {}},
            "成长潜力": {"score": 4.0, "sub_dimensions": {}},
            "基础资质条件": {"score": 3.0, "sub_dimensions": {}},
        },
    }
    result = build_radar_option(scoring)

    assert len(result["indicators"]) == 6
    assert all(ind["max"] == 5 for ind in result["indicators"])
    assert result["values"] == [4.0, 3.0, 3.5, 3.5, 4.0, 3.0]
    assert result["total_score"] == 3.5


def test_build_radar_option_none_scoring():
    result = build_radar_option(None)

    assert len(result["indicators"]) == 6
    assert result["values"] == [0, 0, 0, 0, 0, 0]
    assert result["total_score"] == 0


def test_build_radar_option_indicators_match_top_dimensions():
    result = build_radar_option(None)
    names = [ind["name"] for ind in result["indicators"]]
    assert names == TOP_DIMENSIONS


def test_build_radar_option_missing_dimension_defaults_zero():
    scoring = {
        "total_dim_score": 2.0,
        "dimensions": {
            "专业技术能力": {"score": 4.0, "sub_dimensions": {}},
        },
    }
    result = build_radar_option(scoring)

    assert result["values"][0] == 4.0
    assert result["values"][1:] == [0, 0, 0, 0, 0]
