"""B3-1 L1 提取：JSON-LD(JobPosting) → og/meta → 正文，逐级降级。

用例里刻意放了两条**"不许填"**的断言（公司名）：

- `og:site_name` 是**站点名**（"BOSS直聘"），不是公司名。把它映射进 `company`
  等于往库里灌假数据 —— 用户明确拒绝过"编造数据"，所以这条要有测试钉住。
- og 层不从标题里猜公司（各家标题格式不一，猜错就是永久脏数据）。
"""

from __future__ import annotations

from app.core.link_enrich.extract import extract_page, strip_html_text

FULL_JSONLD = """
<html><head><title>忽略我</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "高级 Java 开发工程师",
  "description": "<p>负责核心交易系统</p><ul><li>高并发</li><li>分布式</li></ul>",
  "hiringOrganization": {"@type": "Organization", "name": "示例科技有限公司"},
  "jobLocation": {"@type": "Place", "address": {
      "@type": "PostalAddress", "addressLocality": "深圳市", "addressRegion": "广东省"
  }},
  "baseSalary": {"@type": "MonetaryAmount", "currency": "CNY",
      "value": {"@type": "QuantitativeValue", "minValue": 20000, "maxValue": 35000, "unitText": "MONTH"}},
  "industry": "互联网",
  "educationRequirements": {"@type": "EducationalOccupationalCredential", "credentialCategory": "本科"},
  "experienceRequirements": {"@type": "OccupationalExperienceRequirements", "monthsOfExperience": 36},
  "qualifications": "熟悉 JVM 调优"
}
</script></head>
<body><nav>首页 登录 注册</nav><div class="job-detail"><p>正文占位</p></div></body></html>
"""

GRAPH_JSONLD = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebSite","name":"某招聘网"},
  {"@type":"JobPosting","title":"数据分析师","hiringOrganization":{"name":"图谱公司"}}
]}
</script></head><body><p>x</p></body></html>
"""

BROKEN_JSONLD_THEN_OG = """
<html><head>
<script type="application/ld+json">{ "@type": "JobPosting", "title": 坏掉的 JSON }</script>
<meta property="og:title" content="产品经理" />
<meta property="og:description" content="负责需求分析与版本规划" />
<meta property="og:site_name" content="BOSS直聘" />
</head><body><p>x</p></body></html>
"""

OG_WITH_SITE_NAME_ONLY = """
<html><head>
<meta property="og:site_name" content="BOSS直聘" />
</head><body><div class="content">这里只有正文，没有任何结构化数据。</div></body></html>
"""


class TestJsonLdTier:
    def test_maps_full_jobposting(self):
        facts = extract_page(FULL_JSONLD, url="https://a.com/j/1")
        f = facts.fields
        assert f["title"] == "高级 Java 开发工程师"
        assert f["company"] == "示例科技有限公司"
        assert "jsonld" in facts.tiers_hit

    def test_location_split_into_city_and_region(self):
        facts = extract_page(FULL_JSONLD)
        # 提取层**原样保留页面写法**（"深圳市"），短名归一化是合并层的事
        # （`merge._normalise_for_fill` → `normalise_geo_name`，见 merge 测试）。
        # 分层别搞混：这里若提前归一化，就再也看不出链接原文写的是什么了。
        assert facts.fields["city"] == "深圳市"
        assert facts.fields["region"] == "广东省"

    def test_salary_is_formatted_and_within_column_width(self):
        facts = extract_page(FULL_JSONLD)
        salary = facts.fields["salary"]
        assert "20000" in salary and "35000" in salary
        assert len(salary) <= 50  # salary_range VARCHAR(50)

    def test_description_html_is_stripped_to_text(self):
        facts = extract_page(FULL_JSONLD)
        desc = facts.fields["description"]
        assert "<p>" not in desc and "<li>" not in desc
        assert "负责核心交易系统" in desc
        assert "高并发" in desc

    def test_education_and_experience_and_qualifications(self):
        facts = extract_page(FULL_JSONLD)
        assert facts.fields["education_requirement"] == "本科"
        assert "36" in facts.fields["experience_requirement"]
        assert "JVM" in facts.fields["requirements"]

    def test_graph_form_is_unwrapped(self):
        facts = extract_page(GRAPH_JSONLD)
        assert facts.fields["title"] == "数据分析师"
        assert facts.fields["company"] == "图谱公司"

    def test_broken_jsonld_falls_back_to_og(self):
        facts = extract_page(BROKEN_JSONLD_THEN_OG)
        assert facts.fields["title"] == "产品经理"
        assert "og" in facts.tiers_hit
        assert "jsonld" not in facts.tiers_hit


class TestMetaTier:
    def test_og_title_and_description_used(self):
        facts = extract_page(BROKEN_JSONLD_THEN_OG)
        assert "需求分析" in facts.fields["description"]

    def test_site_name_is_never_mapped_to_company(self):
        # 站点名（BOSS直聘）不是公司名：映射它 = 灌假数据
        for html in (BROKEN_JSONLD_THEN_OG, OG_WITH_SITE_NAME_ONLY):
            facts = extract_page(html)
            assert "company" not in facts.fields, html
            assert facts.fields.get("company") != "BOSS直聘"

    def test_page_title_tag_is_a_title_fallback(self):
        facts = extract_page("<html><head><title>某岗位 - 某公司</title></head><body>x</body></html>")
        assert facts.fields["title"] == "某岗位 - 某公司"


class TestTextTier:
    def test_text_only_fills_description_not_other_fields(self):
        facts = extract_page(OG_WITH_SITE_NAME_ONLY)
        assert facts.fields.get("description")
        assert "这里只有正文" in facts.fields["description"]
        # 正文层绝不硬拆字段：拆出来的错值比空值更糟
        assert "company" not in facts.fields
        assert "salary" not in facts.fields
        assert "city" not in facts.fields

    def test_tiers_hit_records_text_layer(self):
        facts = extract_page("<html><body><div class='content'>" + "很长的一段岗位描述。" * 3 + "</div></body></html>")
        assert "text" in facts.tiers_hit


class TestTierPriority:
    def test_jsonld_beats_og_for_same_field(self):
        html = """
        <html><head>
        <meta property="og:title" content="OG 标题" />
        <meta property="og:description" content="OG 描述" />
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"JSONLD 标题","description":"<p>JSONLD 描述</p>"}
        </script></head><body><p>x</p></body></html>
        """
        facts = extract_page(html)
        assert facts.fields["title"] == "JSONLD 标题"
        assert "JSONLD 描述" in facts.fields["description"]
        assert facts.tier_of["title"] == "jsonld"

    def test_og_fills_only_what_jsonld_left_empty(self):
        html = """
        <html><head>
        <meta property="og:description" content="OG 补充描述" />
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"只有标题"}
        </script></head><body><p>x</p></body></html>
        """
        facts = extract_page(html)
        assert facts.fields["title"] == "只有标题"
        assert "OG 补充描述" in facts.fields["description"]
        assert facts.tier_of["description"] == "og"


class TestRobustness:
    def test_malformed_html_does_not_raise(self):
        facts = extract_page(b"<html><body><div><span>unclosed")
        assert facts.error is None or isinstance(facts.error, str)

    def test_binary_garbage_does_not_raise(self):
        facts = extract_page(b"\x00\x01\x02 not really html \xff\xfe")
        assert isinstance(facts.fields, dict)

    def test_bytes_input_uses_document_declared_charset(self):
        # 中文站大量用 GBK 且只在 meta 里声明：必须按文档内声明解码，
        # 否则公司名会变成乱码写进库
        html = (
            '<html><head><meta charset="gb2312">'
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"后端开发工程师","hiringOrganization":{"name":"某某科技"}}'
            "</script></head><body>x</body></html>"
        ).encode("gb2312")
        facts = extract_page(html)
        assert facts.fields["title"] == "后端开发工程师"
        assert facts.fields["company"] == "某某科技"

    def test_long_text_is_clipped_with_visible_marker(self):
        html = f'<html><body><div class="content">{"岗位描述" * 500}</div></body></html>'
        facts = extract_page(html, max_text_chars=200)
        assert len(facts.fields["description"]) <= 200
        assert facts.fields["description"].endswith("…")  # 截断必须可见


class TestStripHtmlText:
    def test_block_tags_become_line_breaks(self):
        assert "第一行\n第二行" in strip_html_text("<p>第一行</p><p>第二行</p>")

    def test_plain_text_passthrough(self):
        assert strip_html_text("没有标签") == "没有标签"

    def test_empty(self):
        assert strip_html_text("") == ""
