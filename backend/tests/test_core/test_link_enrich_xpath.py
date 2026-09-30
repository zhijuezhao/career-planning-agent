"""L2 的 XPath 机制：白名单校验、稳定定位式、候选生成。

这组用例的重点是**安全**与**自洽**：

- 安全：模型产出的表达式在**执行前**必须过白名单。XPath 不能执行代码，所以风险是
  DoS（对 2MB 文档做全节点子串匹配）而不是 RCE —— 但"没有 RCE"不等于"可以随便执行"。
- 自洽：**本模块自己生成的表达式必须能通过本模块自己的校验**。这条看着废话，
  实际上救过一次：字符白名单一开始漏了逗号，而主力形状 `concat(" ", ...)` 需要逗号
  → 所有候选都会被自己的校验器拒掉，表现为"候选永远为空"且**不报错**。
"""

from __future__ import annotations

import pytest
from app.core.link_enrich.xpath import (
    EXTRACTABLE_FIELDS,
    apply_xpath,
    build_xpath_candidates,
    candidates_by_field,
    stable_xpath_for,
    validate_xpath,
)
from lxml import html as lxml_html


def _tree(doc: str):
    return lxml_html.document_fromstring(doc)


SAMPLE = """
<html><body>
  <div class="job-header">
    <span class="company-name">示例科技有限公司</span>
  </div>
  <div class="job-salary">20-30K·13薪</div>
  <ul class="job-meta">
    <li class="job-location">深圳</li>
    <li class="job-edu">本科</li>
  </ul>
  <div><span class="label">行业</span><span class="value">互联网</span></div>
  <nav class="site-nav">首页 登录 注册</nav>
</body></html>
"""


class TestValidateXpath:
    def test_accepts_the_shapes_we_generate(self):
        ok = [
            "//*[@id='salary']",
            '//span[contains(concat(" ", normalize-space(@class), " "), \'job-salary\')]',
            "//div[@class='a'][1]",
            "//span[contains(text(), '薪')]",
            # 「标签-值」配对定位式：`contains(.)` 作用在**具体标签**上是正常的，
            # 只有 `//*[contains(., …)]` 才是性能陷阱
            '//li[contains(., \'薪资\')]/span[contains(concat(" ", normalize-space(@class), " "), \'p-value\')]',
        ]
        for expr in ok:
            assert validate_xpath(expr) is None, expr

    @pytest.mark.parametrize(
        "expr,expect",
        [
            ("", "空"),
            (None, "空"),
            ("   ", "空"),
            ("div[@id='a']", "// 开头"),
            ("/html/body/div", "// 开头"),
            ("//a | //b", "联合"),
            ("//div/following-sibling::div", "轴"),
            ("//*[document('http://x')]", "document"),
            ("//*[@*]", "@*"),
            ("//div/../span", "父节点"),
            ("//*[contains(., '薪')]", "全节点子串匹配"),
            ("//*[@a][@b][@c][@d][@e]", "谓词过多"),
            ("//a//b//c//d", "// 段数过多"),
            ("//*[foo('x')]", "不允许的函数"),
            ("//*[system('x')]", "不允许的函数"),
            ("//*[@id='a'", "谓词"),
            ("//*[@id=$var]", "字符"),
            ("//*[`x`]", "字符"),
            ("//" + "a" * 300, "过长"),
        ],
    )
    def test_rejects_dangerous_or_malformed(self, expr, expect):
        reason = validate_xpath(expr)
        assert reason is not None, expr
        assert expect in reason, (expr, reason)

    def test_own_generated_expressions_always_pass(self):
        """本模块生成的表达式必须过本模块的校验（漏逗号那次就是这条会红）。"""
        tree = _tree(SAMPLE)
        for element in tree.iter():
            if not isinstance(element.tag, str):
                continue
            expr = stable_xpath_for(element, tree)
            if expr:
                assert validate_xpath(expr) is None, expr


class TestStableXpathFor:
    def test_prefers_id(self):
        tree = _tree("<html><body><div id='job-detail'>x</div></body></html>")
        element = tree.xpath("//div[@id='job-detail']")[0]
        assert stable_xpath_for(element, tree) == "//*[@id='job-detail']"

    def test_uses_longest_class_token(self):
        tree = _tree("<html><body><div class='a job-salary-value'>x</div></body></html>")
        element = tree.xpath("//div")[0]
        expr = stable_xpath_for(element, tree)
        # 越长的 class 词越具体，越不容易在别的字段上重复出现
        assert "job-salary-value" in expr

    def test_uses_name_attribute(self):
        tree = _tree("<html><body><input name='company' /></body></html>")
        element = tree.xpath("//input")[0]
        assert "name" in stable_xpath_for(element, tree)

    def test_gives_up_when_there_is_no_anchor(self):
        # 绝对路径（/html/body/div[3]）在**同一站的第二页**必然失效，
        # 而 L2 的全部价值就是同域复用 → 宁可不给候选
        tree = _tree("<html><body><div><span>没有锚点</span></div></body></html>")
        assert stable_xpath_for(tree.xpath("//span")[0], tree) is None


class TestApplyXpath:
    def test_returns_text(self):
        tree = _tree(SAMPLE)
        assert apply_xpath(tree, "//*[@id='x']") == []
        values = apply_xpath(tree, "//li[@class='job-location']")
        assert values == ["深圳"]

    def test_rejects_unvalidated_expression_without_raising(self):
        tree = _tree(SAMPLE)
        assert apply_xpath(tree, "//a | //b") == []

    def test_bad_expression_returns_empty(self):
        tree = _tree(SAMPLE)
        assert apply_xpath(tree, "//*[unclosed") == []

    def test_node_limit(self):
        tree = _tree("<html><body>" + "<p>行</p>" * 10 + "</body></html>")
        assert len(apply_xpath(tree, "//p", limit=3)) == 3

    def test_none_tree(self):
        assert apply_xpath(None, "//p") == []


class TestBuildCandidates:
    def test_finds_fields_by_class_keywords(self):
        tree = _tree(SAMPLE)
        grouped = candidates_by_field(build_xpath_candidates(tree))
        assert "job-salary" in str([c.xpath for c in grouped.get("salary", [])])
        assert grouped.get("company"), "公司字段应找到候选"

    def test_label_value_sibling_rule(self):
        """`<span class="label">行业</span><span class="value">互联网</span>`

        值所在元素的 class 是泛化的 `value`，没有任何"行业"字样 —— 只靠关键词匹配
        永远找不到它。所以"自身文本命中关键词 → 下一个兄弟元素"这条规则必须有。
        """
        tree = _tree(SAMPLE)
        grouped = candidates_by_field(build_xpath_candidates(tree))
        industry = grouped.get("industry", [])
        assert industry, "应通过标签-值规则找到行业的值元素"
        assert any("互联网" in c.preview for c in industry)

    def test_pair_locator_disambiguates_repeated_classes(self):
        """中文岗位页的典型形态：同一种值 class 在多行上重复出现。

        `<li><span class="p-label">薪资</span><span class="p-value">25-40K</span></li>`
        与城市/经验/学历/行业四行结构完全相同 —— 只按 `p-value` 定位会**匹配 5 个**，
        取第一个在本文档碰巧对，换一页顺序一变就**静默取错值**。
        所以必须生成"按标签文字锚定那一行"的配对定位式，并且只保留验证过唯一的。
        """
        page = """
        <html><body><ul class="job-params">
          <li><span class="p-label">薪资</span><span class="p-value">25-40K</span></li>
          <li><span class="p-label">城市</span><span class="p-value">深圳市南山区</span></li>
          <li><span class="p-label">经验</span><span class="p-value">5-10年</span></li>
          <li><span class="p-label">学历</span><span class="p-value">本科及以上</span></li>
        </ul></body></html>
        """
        tree = _tree(page)
        grouped = candidates_by_field(build_xpath_candidates(tree))

        salary = grouped.get("salary", [])
        assert salary, "应找到薪资候选"
        best = salary[0]
        assert "contains(., '薪资')" in best.xpath, best.xpath
        assert best.matches == 1, "配对定位式必须唯一（否则会静默取错值）"
        assert best.preview == "25-40K"
        assert validate_xpath(best.xpath) is None

    def test_ambiguous_locators_are_deprioritised(self):
        page = """
        <html><body><ul>
          <li><span class="p-label">薪资</span><span class="p-value">25-40K</span></li>
          <li><span class="p-label">城市</span><span class="p-value">深圳</span></li>
        </ul></body></html>
        """
        tree = _tree(page)
        salary = candidates_by_field(build_xpath_candidates(tree))["salary"]
        # 排序键是 (score desc, matches asc)：唯一的配对定位式必须排在最前
        assert salary[0].matches == 1
        assert salary[0].score == max(c.score for c in salary)

    def test_every_candidate_resolves_to_text(self):
        tree = _tree(SAMPLE)
        for candidate in build_xpath_candidates(tree):
            assert validate_xpath(candidate.xpath) is None
            assert apply_xpath(tree, candidate.xpath), candidate

    def test_respects_field_and_total_limits(self):
        tree = _tree(SAMPLE)
        candidates = build_xpath_candidates(tree, per_field_limit=1, total_limit=3)
        assert len(candidates) <= 3
        assert len({c.field for c in candidates}) <= 3

    def test_empty_and_none_trees(self):
        assert build_xpath_candidates(None) == []
        assert build_xpath_candidates(_tree("<html><body></body></html>")) == []

    def test_unknown_fields_ignored(self):
        tree = _tree(SAMPLE)
        assert build_xpath_candidates(tree, ["not_a_field"]) == []

    def test_extractable_fields_exclude_long_text(self):
        # description/requirements 由 L1 正文提取负责：长文本用一条 XPath 重新定位
        # 收益低、失效概率高
        assert "description" not in EXTRACTABLE_FIELDS
        assert "requirements" not in EXTRACTABLE_FIELDS


class TestAsciiKeywordWordBoundary:
    """§31.11 ②（2026-09-29 用户裁决）：ASCII 关键词按**词元**匹配，不做子串。

    ⚠️ 交接文档原先把这一项描述成"候选生成偏中文、要补英文词表" —— **实测证明那是错的**：
    `FIELD_KEYWORDS` 里 `salary` / `location` / `experience` / `company` 等英文词**本来就有**，
    真实 Lever 页上也没有 `Salary`/`Level`/`Education` 这类**标签**（正则计数为 0），
    那些字段拿到 0 个候选是**正确行为**。真正的毛病是**短英文词按子串误命中**：

        `org` ⊂ `Georgia`     → 那个"地点列表" <div> 成了 `company` 的候选
        `category` ⊂ class    → 同一个 <div> 又成了 `industry` 的候选

    于是**同一个元素同时是 city/company/industry/salary 四个字段的候选** —— 正是坑 21 的
    "静默取错值"。所以修法是**改匹配方式**，不是加词（加词只会加更多假阳性）。
    """

    def test_short_ascii_keyword_does_not_match_inside_a_word(self):
        """`Georgia` 含子串 `org`，但那不代表这个元素是公司（真实 Lever 页的形态）。"""
        page = """
        <html><body>
          <div class="posting-category medium-category-label location">
            Atlanta, Georgia / Arlington, TX / Boston, MA
          </div>
        </body></html>
        """
        grouped = candidates_by_field(build_xpath_candidates(_tree(page)))
        assert not grouped.get("company"), "`org` 不该命中 `Georgia` 的子串"

    def test_hyphenated_class_still_matches_by_token(self):
        """连字符就是词边界 —— `location` 仍必须命中真实的长 class 名（别修过头）。"""
        page = """
        <html><body>
          <span id="secondary-additional-location-boston">Boston, MA</span>
        </body></html>
        """
        grouped = candidates_by_field(build_xpath_candidates(_tree(page)))
        assert grouped.get("city"), "`location` 应命中 `secondary-additional-location-boston`"

    def test_english_class_keywords_still_match(self):
        """正例：词表里的英文词在**词边界**上依然命中（修的是假阳性，不是砍功能）。"""
        page = """
        <html><body>
          <div class="job-salary">$120,000 - $150,000</div>
          <div class="company-name">Acme Inc</div>
          <div class="job-experience">3+ years</div>
        </body></html>
        """
        grouped = candidates_by_field(build_xpath_candidates(_tree(page)))
        assert grouped.get("salary"), "`salary` 应命中 `job-salary`"
        assert grouped.get("company"), "`company` 应命中 `company-name`"
        assert grouped.get("experience_requirement"), "`experience`/`years` 应命中"

    def test_cjk_keywords_still_match_as_substring(self):
        """中文没有词边界概念 → 子串是唯一可行的判据（`薪资` 命中 `岗位薪资`）。"""
        page = """
        <html><body>
          <div class="岗位薪资">25-40K·13薪</div>
        </body></html>
        """
        grouped = candidates_by_field(build_xpath_candidates(_tree(page)))
        assert grouped.get("salary"), "中文关键词必须仍走子串匹配"

    def test_chinese_label_value_pairing_survives(self):
        """词边界改动**不能**碰坏坑 21 那条"标签-值"配对定位式。"""
        page = """
        <html><body><ul>
          <li><span class="p-label">薪资</span><span class="p-value">25-40K</span></li>
          <li><span class="p-label">城市</span><span class="p-value">杭州</span></li>
        </ul></body></html>
        """
        grouped = candidates_by_field(build_xpath_candidates(_tree(page)))
        salary = grouped.get("salary", [])
        assert salary, "中文标签-值结构应产出薪资候选"
        assert "contains(., '薪资')" in salary[0].xpath, salary[0].xpath
