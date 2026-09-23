"""P1-4：快照 Markdown 导出渲染器（纯函数，零 IO、零数据库）。"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.domain.services import snapshot_markdown


def _snapshot(**overrides) -> SimpleNamespace:
    base = {
        "id": 7,
        "user_id": 42,
        "serial_no": uuid4(),
        "description": "测试快照",
        "matched_at": datetime(2026, 9, 23, 10, 30, 0),
        "created_at": datetime(2026, 9, 23, 10, 0, 0),
        "five_layers_json": {"基础信息": {"姓名": "张三", "技能": ["Python", "SQL"]}},
        "six_dim_scores_json": {"技能": 4.2, "实践": 3.8},
        "form_raw_json": {"姓名": "张三"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestSnapshotMarkdown:
    def test_renders_meta_and_all_sections(self):
        text = snapshot_markdown.render(_snapshot(), username="s7admin")

        assert text.startswith("# 画像快照 ")
        assert "- **快照ID**：7" in text
        assert "- **用户ID**：42" in text
        assert "- **用户名**：s7admin" in text
        assert "- **匹配状态**：已匹配" in text
        assert "## 五层画像" in text
        assert "### 基础信息" in text
        assert "- **姓名**：张三" in text
        assert "- Python" in text
        assert "## 六维分数" in text
        assert "| 技能 | 4.2 |" in text
        assert "## 原始表单（附录）" in text
        assert '"姓名": "张三"' in text

    def test_unmatched_snapshot_says_pending(self):
        text = snapshot_markdown.render(_snapshot(matched_at=None))
        assert "- **匹配状态**：待匹配" in text
        assert "匹配时间" not in text

    def test_missing_username_line_is_skipped(self):
        text = snapshot_markdown.render(_snapshot(), username=None)
        assert "- **用户名**" not in text

    def test_empty_snapshot_still_has_title(self):
        text = snapshot_markdown.render(
            _snapshot(five_layers_json=None, six_dim_scores_json=None, form_raw_json=None)
        )
        assert text.startswith("# 画像快照 ")
        assert "## 五层画像" not in text
        assert "## 六维分数" not in text
        assert text.endswith("\n")

    def test_long_value_is_truncated(self):
        text = snapshot_markdown.render(
            _snapshot(five_layers_json={"自我评价": "长" * 3000})
        )
        assert "（已截断）" in text
        assert len(text) < 6000

    def test_empty_nested_value_renders_placeholder(self):
        text = snapshot_markdown.render(_snapshot(five_layers_json={"技能": []}))
        assert "### 技能" in text
        assert "（暂无）" in text
