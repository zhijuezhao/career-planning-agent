"""B3-1 L0 层：URL 发现与规范化（纯本地，零网络）。

这些用例守的是"表格里的链接能不能被正确挖出来、会不会被尾巴上的标点带歪"。
实测踩过的坑：中文表格里链接常写在 `详情：https://...。` 里，尾随的全角句号
如果没剥掉，抓取时会变成 404（路径里多了个 `。`）。
"""

from __future__ import annotations

from app.core.link_enrich.urls import (
    discover_row_urls,
    domain_of,
    find_urls,
    group_by_domain,
    normalise_url,
    url_hash,
)


class TestFindUrls:
    def test_extracts_plain_url(self):
        assert find_urls("https://jobs.example.com/posting/1") == [
            "https://jobs.example.com/posting/1"
        ]

    def test_extracts_url_embedded_in_chinese_text(self):
        # 真实表格形态：「详情见 https://a.com/j/1 有意者联系」
        found = find_urls("详情见 https://a.com/j/1 有意者联系")
        assert found == ["https://a.com/j/1"]

    def test_strips_trailing_chinese_punctuation(self):
        # 这是 404 的根因：中文句号不能被当成路径的一部分
        assert find_urls("https://a.com/j/1。") == ["https://a.com/j/1"]
        assert find_urls("（https://a.com/j/1）") == ["https://a.com/j/1"]
        assert find_urls("https://a.com/j/1，有意者") == ["https://a.com/j/1"]

    def test_multiple_urls_preserve_order_and_dedupe(self):
        found = find_urls("https://a.com/1 和 https://b.com/2 再来一次 https://a.com/1")
        assert found == ["https://a.com/1", "https://b.com/2"]

    def test_non_string_and_empty_inputs(self):
        assert find_urls(None) == []
        assert find_urls("") == []
        assert find_urls(12345) == []
        assert find_urls(["https://a.com/1"]) == []

    def test_ignores_non_http_schemes(self):
        assert find_urls("ftp://a.com/f") == []
        assert find_urls("file:///etc/passwd") == []


class TestNormaliseUrl:
    def test_lowercases_host_and_keeps_query(self):
        # query 必须保留：很多站点的岗位 id 就在 query 里，
        # 去掉它会让不同岗位共用一个缓存键
        assert normalise_url("HTTPS://Jobs.Example.COM/a?jobId=7") == (
            "https://jobs.example.com/a?jobId=7"
        )

    def test_drops_fragment(self):
        assert normalise_url("https://a.com/j/1#apply") == "https://a.com/j/1"

    def test_drops_default_port(self):
        assert normalise_url("https://a.com:443/x") == "https://a.com/x"
        assert normalise_url("http://a.com:80/x") == "http://a.com/x"

    def test_keeps_non_default_port(self):
        assert normalise_url("https://a.com:8443/x") == "https://a.com:8443/x"

    def test_empty_path_becomes_slash(self):
        assert normalise_url("https://a.com") == "https://a.com/"

    def test_garbage_returns_empty(self):
        assert normalise_url("") == ""
        assert normalise_url("not a url") == ""


class TestUrlHashAndDomain:
    def test_hash_is_64_hex_chars(self):
        # 必须与 link_fetch_cache.url_hash VARCHAR(64) 严丝合缝
        digest = url_hash("https://a.com/j/1")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_equivalent_urls_share_a_hash(self):
        # 大小写 / fragment / 默认端口 / 尾随标点都不该产生新的缓存键
        canonical = url_hash("https://a.com/j/1")
        assert url_hash("HTTPS://A.com/j/1#x") == canonical
        assert url_hash("https://a.com:443/j/1") == canonical
        assert url_hash("https://a.com/j/1。") == canonical

    def test_different_query_is_different_hash(self):
        assert url_hash("https://a.com/j?id=1") != url_hash("https://a.com/j?id=2")

    def test_domain_strips_www(self):
        assert domain_of("https://www.zhipin.com/job/1") == "zhipin.com"
        assert domain_of("https://jobs.example.com/x") == "jobs.example.com"


class TestDiscoverRowUrls:
    def test_scans_all_string_cells(self):
        row = {"title": "Java 工程师", "备注": "见 https://a.com/j/1"}
        assert discover_row_urls(row) == ["https://a.com/j/1"]

    def test_source_url_key_wins_over_other_keys(self):
        # data_loader 已把「岗位链接」等列名统一映射到 source_url。
        # 官方链接列必须优先，而不是靠字典顺序碰运气。
        row = {
            "备注": "参考 https://other.com/x",
            "source_url": "https://official.com/j/1",
        }
        assert discover_row_urls(row)[0] == "https://official.com/j/1"

    def test_per_row_limit_caps_runaway_cells(self):
        row = {"note": " ".join(f"https://a.com/{i}" for i in range(10))}
        assert len(discover_row_urls(row, per_row_limit=3)) == 3

    def test_row_without_urls(self):
        assert discover_row_urls({"title": "Java", "city": "深圳"}) == []

    def test_non_dict_row(self):
        assert discover_row_urls("https://a.com/1") == []


class TestGroupByDomain:
    def test_groups_and_preserves_order(self):
        grouped = group_by_domain(
            ["https://a.com/1", "https://b.com/2", "https://a.com/3"]
        )
        assert list(grouped) == ["a.com", "b.com"]
        assert grouped["a.com"] == ["https://a.com/1", "https://a.com/3"]
