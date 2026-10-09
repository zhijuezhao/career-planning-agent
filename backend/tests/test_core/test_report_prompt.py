from app.core.llm.prompts.profile_analysis import REPORT_GENERATION_SYSTEM_PROMPT, build_report_messages


def test_prompt_has_six_modules():
    for mod in ("模块一 个人概况", "模块二 能力优势分析", "模块三 待提升领域",
                "模块四 岗位匹配对比分析", "模块五 职业匹配建议", "模块六 成长路径建议"):
        assert mod in REPORT_GENERATION_SYSTEM_PROMPT

def test_prompt_word_count_range():
    assert "1500-2000" in REPORT_GENERATION_SYSTEM_PROMPT

def test_build_messages_injects_matching_results():
    msgs = build_report_messages(
        five_layers_json='{"intention": {}}',
        dimension_scoring_json='{}',
        basic_info_json='{"name": "张三"}',
        matching_results_json='[{"job_profile_id": 1, "match_score": 0.85}]',
    )
    user_text = msgs[-1]["content"]
    assert "job_profile_id" in user_text and "0.85" in user_text
