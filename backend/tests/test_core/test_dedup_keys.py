"""B2（2026-10-03）单元测试：去重键 / 来源链接归一化。

`normalise_source_url` 存在的理由（实测用户真实数据）：
    智联岗位详情 URL 形如::

        https://www.zhaopin.com/jobdetail/CC383625320J40658720509.htm
            ?refcode=4019&srccode=401901&preactionid=<导出会话id>

    其中 `preactionid` 在**一次导出里只有一个值**（524 行全表就 1 个值）—— 它是
    **导出会话 id**，用户下次重新导出同一批岗位时一定会变。所以完整 URL 不能当
    去重键/幂等键，否则"同一份表再导一次"会被判成一批全新岗位。
"""

from __future__ import annotations

from app.core.dedup_keys import (
    job_dedup_key,
    normalise_company_name,
    normalise_source_url,
    normalise_title,
)


class TestNormaliseSourceUrl:
    def test_strips_query_string(self):
        assert (
            normalise_source_url("https://x.com/j/1.htm?refcode=1&preactionid=AAA")
            == "https://x.com/j/1.htm"
        )

    def test_strips_fragment(self):
        assert normalise_source_url("https://x.com/j/1.htm#top") == "https://x.com/j/1.htm"

    def test_two_exports_of_same_job_share_identity(self):
        """核心用例：同一岗位在不同导出批次里的会话参数不同，但必须归一成同一个值。"""
        a = normalise_source_url("https://x.com/j/CC1.htm?preactionid=AAA&refcode=1")
        b = normalise_source_url("https://x.com/j/CC1.htm?preactionid=BBB&refcode=1")
        assert a == b == "https://x.com/j/CC1.htm"

    def test_plain_url_unchanged(self):
        assert normalise_source_url("https://x.com/j/CC1.htm") == "https://x.com/j/CC1.htm"

    def test_placeholders_return_none(self):
        for value in (None, "", "  ", "None", "nan", "null", "-", "未知", "无"):
            assert normalise_source_url(value) is None, value


class TestJobDedupKeyUnchanged:
    """B2 没有改动 `(岗位名, 公司)` 这一级的规则，锁住原有语义。"""

    def test_title_case_and_whitespace_collapsed(self):
        assert normalise_title("  Java  开发 ") == "java 开发"

    def test_company_empty_string_when_placeholder(self):
        assert normalise_company_name("未知") is None
        assert job_dedup_key("Java", None) == ("java", "")
        assert job_dedup_key("Java", "ABC") == ("java", "ABC")
