"""L1 层：抓到的页面 → 结构化字段（零 LLM）。

分层优先级（主计划 §4.1 L1）：**JSON-LD（schema.org JobPosting）→ og/meta → 正文提取**。
上一级能填的字段绝不用下一级的，避免劣币驱逐良币。

## 两条刻意的"不填"

1. **`og:site_name` 不映射到 `company`**。它给的是**站点名**（"BOSS直聘"、
   "智联招聘"），写进公司字段就是往库里灌假数据 —— 用户明确拒绝过"编造数据"。
   同理不从 `og:title` 里猜公司（标题格式各家不一，猜错就是永久脏数据）。
2. **正文（text 层）只用于补 `description`**，不从中硬拆字段。B3-1 是零 LLM 层，
   没有可靠手段从自由文本里定位薪酬/学历；硬拆出来的错值比空值更糟（§4.2 第 2 点
   "数据污染"）。字段级的正文抽取留给 B3-2 的 XPath/LLM 层。

## 为什么用 lxml 而不是 httpx 的 `.text`

中文招聘站大量用 GBK/gb2312，且常**只在 `<meta charset>` 里声明**、HTTP 头不带
charset。把原始 bytes 交给 lxml，它会按文档内声明解码；先让 httpx `.text` 猜一遍
反而会得到乱码。解析器固定 `resolve_entities=False, no_network=True`，
与 §11「XPath 只在安全解析器上执行」同一口径（B3-2 复用同一棵树）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from lxml import html as lxml_html

try:  # 正文提取：装了就用，没装退回确定性启发式（保证镜像里没有它也能跑）
    import trafilatura
except ImportError:  # pragma: no cover - 取决于镜像是否装了 trafilatura
    trafilatura = None

#: 页面里真正可能承载岗位信息的 <script> 类型
_JSONLD_TYPE = "application/ld+json"

def _class_xpath(name: str) -> str:
    """`//*[contains(concat(" ", normalize-space(@class), " "), " name ")]`。

    这里刻意**不用 CSS 选择器**：`tree.cssselect()` 需要额外的 `cssselect` 包，
    而它不是 lxml 的必装依赖 —— 依赖一个可能不存在的包，会在线上第一条链接上
    才炸出来。XPath 是 lxml 自带的。
    """
    return f'//*[contains(concat(" ", normalize-space(@class), " "), " {name} ")]'


#: 正文容器的候选（按"越具体越优先"排列，实现是 XPath）
_CONTENT_XPATHS = (
    "//article",
    "//main",
    '//*[@role="main"]',
    _class_xpath("job-detail"),
    _class_xpath("job-detail-content"),
    _class_xpath("job-sec"),
    _class_xpath("job-description"),
    _class_xpath("detail-content"),
    _class_xpath("content"),
    '//*[@id="content"]',
)

#: 正文里必须丢掉的结构性噪声
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "svg", "form", "nav", "header", "footer", "aside")

#: 这些标签后面要补一个换行（否则 `text_content()` 会把段落糊成一整坨）
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "tr", "td", "th", "section", "article", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "dd", "dt",
    }
)

#: 一组字段键 → 表格/落库键名（与 `job_persist_service.upsert_job_profile` 读的行键一致）
FIELD_KEYS = (
    "title",
    "company",
    "city",
    "region",
    "salary",
    "industry",
    "level",
    "education_requirement",
    "experience_requirement",
    "description",
    "requirements",
)

_WS_RE = re.compile(r"[ \t\u00a0\u3000]+")
_BLANKLINE_RE = re.compile(r"\n{3,}")

#: 文档内 charset 声明（`<meta charset=gb2312>` / `<meta http-equiv=... content="text/html; charset=gbk">`）
_META_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?\s*([\w-]+)", re.IGNORECASE)

#: 月/年/时 → 中文单位（salary_range VARCHAR(50)，拼出来的串必须短）
_UNIT_CN = {"MONTH": "月", "YEAR": "年", "HOUR": "小时", "DAY": "天", "WEEK": "周"}


@dataclass
class PageFacts:
    """一个页面能确定性拿到的东西。"""

    fields: dict[str, Any] = field(default_factory=dict)
    #: 字段 → 产出它的层级（"jsonld" / "og" / "text"），写进 provenance
    tier_of: dict[str, str] = field(default_factory=dict)
    tiers_hit: tuple[str, ...] = ()
    title: str | None = None
    text: str = ""
    error: str | None = None


# ── 基础清洗 ──────────────────────────────────────────────────────────────


def _collapse(text: str) -> str:
    """压缩空白：中文页面里全角空格与不换行空格都常见，不处理会污染字段值。"""
    if not text:
        return ""
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    joined = "\n".join(line for line in lines if line)
    return _BLANKLINE_RE.sub("\n\n", joined).strip()


def strip_html_text(fragment: str, *, parser=None) -> str:
    """把一段 HTML 片段（JSON-LD 的 `description` 常是 HTML）转成纯文本。

    用 lxml 而不是正则：`<br>`/`<li>` 要变成**换行**，正则做不到。
    `text_content()` 只是把文本节点直接拼起来（`<p>a</p><p>b</p>` → "ab"），
    所以这里先给块级元素补 `tail` 换行 —— 否则岗位描述的段落会糊成一整坨。
    """
    if not fragment:
        return ""
    if "<" not in fragment:
        return _collapse(fragment)
    try:
        node = lxml_html.fragment_fromstring(fragment, create_parent="div", parser=parser)
    except Exception:  # noqa: BLE001 - 片段畸形时退回正则去标签
        return _collapse(re.sub(r"<[^>]+>", "\n", fragment))
    for bad in node.iter("script", "style"):
        bad.getparent().remove(bad)
    for element in node.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.lower() in _BLOCK_TAGS:
            element.tail = (element.tail or "") + "\n"
    return _collapse(node.text_content())


def _clip(text: str, limit: int) -> str:
    """截断并显式打标 —— 让下游知道"这里被截过"，而不是以为原文就这么短。"""
    text = (text or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _safe_parser():
    """安全解析器。

    ⚠️ **不能传 `resolve_entities`**：那是 `XMLParser` 的选项，`lxml.html.HTMLParser`
    会直接 `TypeError`（2026-09-27 实测踩坑：传了它 → 每个页面都返回"HTML 解析失败"）。
    libxml2 的 HTML 解析器本身不做外部实体解析，这里真正起作用的是 `no_network=True`
    —— 禁止解析器因为 DTD/实体去发起网络请求。
    `huge_tree` 保持默认 False：它对文档深度与大小有上限，能挡住"畸形深嵌套"这类
    想拖垮解析器的输入。
    """
    return lxml_html.HTMLParser(no_network=True)


def _to_parseable(html: bytes | str) -> bytes | str:
    """决定交给 lxml 的是 str 还是 bytes —— 这决定了中文会不会变乱码。

    2026-09-27 实测（`lxml 6.1.3`）：

    | 输入 | 结果 |
    |---|---|
    | `str`（"高级 Java"） | ✅ 正确 —— lxml 把 str 编成 UTF-8 并**告知解析器**，所以能正确解回 |
    | `bytes` + 文档内 `<meta charset>` | ✅ 正确 —— 按文档声明解码（GBK 站靠这条路） |
    | `bytes` 且无任何声明 | ❌ **按 Latin-1 解**，中文全成 `é«çº§` |

    所以：str 原样传；bytes 只在"文档自己声明了 charset"时才原样传，否则先自己试
    UTF-8（现代页面无声明的基本都是 UTF-8），解不开再退回 bytes 交给 lxml 碰运气。
    """
    if isinstance(html, str):
        return html
    head = html[:4096].decode("latin-1", errors="ignore")
    if _META_CHARSET_RE.search(head):
        return html
    try:
        return html.decode("utf-8")
    except UnicodeDecodeError:
        return html


def parse_html(html: bytes | str):
    """解析成 lxml 文档树；失败返回 None（畸形页面不该让整单倒下）。"""
    try:
        return lxml_html.document_fromstring(_to_parseable(html), parser=_safe_parser())
    except Exception as exc:  # noqa: BLE001 - 页面畸形种类极多
        logger.debug("HTML 解析失败 | error={}", exc)
        return None


def _first_str(value: Any) -> str:
    """JSON-LD 的字段可能是 str / list / dict，统一取第一个可读字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "description", "credentialCategory"):
            if key in value:
                got = _first_str(value[key])
                if got:
                    return got
        return ""
    if isinstance(value, list):
        for item in value:
            got = _first_str(item)
            if got:
                return got
    return ""


# ── JSON-LD ──────────────────────────────────────────────────────────────


def _iter_jsonld_nodes(tree) -> list[dict]:
    """取出页面里所有 JSON-LD 对象（含 `@graph` 展开与数组形式）。"""
    nodes: list[dict] = []
    for script in tree.xpath(f'//script[@type="{_JSONLD_TYPE}"]'):
        raw = script.text or script.text_content() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001 - 真实站点里 JSON-LD 语法错误很常见
            logger.debug("JSON-LD 解析失败（跳过该块）| len={}", len(raw))
            continue
        stack = [parsed]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.append(item["@graph"])
                nodes.append(item)
    return nodes


def _type_names(node: dict) -> list[str]:
    raw = node.get("@type") or node.get("type") or ""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]


def _format_salary(node: dict) -> str:
    """baseSalary → 短字符串（列宽 50，超了会被 DB 拒绝，必须先收紧）。"""
    salary = node.get("baseSalary")
    if not isinstance(salary, dict):
        return _first_str(salary)[:50]
    currency = _first_str(salary.get("currency")) or _first_str(node.get("salaryCurrency"))
    value = salary.get("value")
    unit = ""
    low = high = ""
    if isinstance(value, dict):
        low = _first_str(value.get("minValue"))
        high = _first_str(value.get("maxValue"))
        unit = _UNIT_CN.get(_first_str(value.get("unitText")).upper(), "")
        if not low and not high:
            low = _first_str(value.get("value"))
    else:
        low = _first_str(value)
    if not (low or high):
        return ""
    if high and high != low:
        amount = f"{low}-{high}"
    else:
        amount = low or high
    parts = [amount]
    if currency:
        parts.append(currency)
    if unit:
        parts.append(f"/{unit}")
    return " ".join(parts)[:50]


def _experience_text(node: dict) -> str:
    """`experienceRequirements` → 可读文本。

    它的形状比其它字段刁钻：可以是字符串、`{"monthsOfExperience": 36}`、
    或 `{"description": "3 年以上"}`。只取 "36" 太隐晦，所以月数补上单位。
    """
    raw = node.get("experienceRequirements")
    if isinstance(raw, dict):
        months = raw.get("monthsOfExperience")
        if months not in (None, ""):
            return f"{months} 个月经验"
        return _first_str(raw)
    return _first_str(raw) or _first_str(node.get("experienceInPlaceOfEducation"))


def _jobposting_to_fields(node: dict, *, max_text_chars: int) -> dict[str, Any]:
    """schema.org JobPosting → 行字段。只填确实存在的键。"""
    fields: dict[str, Any] = {}

    title = _first_str(node.get("title") or node.get("name"))
    if title:
        fields["title"] = _clip(title, 200)

    org = node.get("hiringOrganization")
    company = _first_str(org)
    if company:
        fields["company"] = _clip(company, 200)

    location = node.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, list):
            address = address[0] if address else None
        if isinstance(address, dict):
            city = _first_str(address.get("addressLocality"))
            region = _first_str(address.get("addressRegion"))
            if city:
                fields["city"] = _clip(city, 50)
            if region:
                fields["region"] = _clip(region, 50)

    salary = _format_salary(node)
    if salary:
        fields["salary"] = salary

    industry = _first_str(node.get("industry")) or _first_str(node.get("occupationalCategory"))
    if industry:
        fields["industry"] = _clip(industry, 100)

    education = _first_str(node.get("educationRequirements")) or _first_str(
        node.get("requiredCredential")
    )
    if education:
        fields["education_requirement"] = _clip(education, 50)

    experience = _experience_text(node)
    if experience:
        fields["experience_requirement"] = _clip(experience, 100)

    description = _first_str(node.get("description"))
    if description:
        fields["description"] = _clip(strip_html_text(description), max_text_chars)

    quals = node.get("qualifications") or node.get("skills") or node.get("responsibilities")
    requirements = _first_str(quals)
    if requirements:
        fields["requirements"] = _clip(strip_html_text(requirements), max_text_chars)

    return fields


def extract_jsonld_fields(tree, *, max_text_chars: int) -> dict[str, Any]:
    """在整棵树上找第一个 JobPosting 节点并映射；没有则返回空 dict。"""
    best: dict[str, Any] = {}
    for node in _iter_jsonld_nodes(tree):
        names = {name.lower() for name in _type_names(node)}
        if not any("jobposting" in name for name in names):
            continue
        mapped = _jobposting_to_fields(node, max_text_chars=max_text_chars)
        # 多个 JobPosting（列表页）时取"填得最全"的那个，而不是第一个
        if len(mapped) > len(best):
            best = mapped
    return best


# ── og / meta ────────────────────────────────────────────────────────────


def extract_meta_fields(tree, *, max_text_chars: int) -> dict[str, Any]:
    """og / meta 层：**只**产出 title 与 description。

    刻意不碰 `og:site_name`（站点名 ≠ 公司名）—— 见模块 docstring 第 1 条。
    """
    fields: dict[str, Any] = {}

    def _meta(*keys: str) -> str:
        for key in keys:
            for node in tree.xpath(f'//meta[translate(@property,"OG:","og:")="{key}"]'):
                value = (node.get("content") or "").strip()
                if value:
                    return value
        return ""

    title = _meta("og:title") or _meta("twitter:title")
    if not title:
        title_node = tree.find(".//title")
        title = (title_node.text or "").strip() if title_node is not None else ""
    if title:
        fields["title"] = _clip(_collapse(title), 200)

    description = _meta("og:description") or _meta("twitter:description") or _meta("description")
    if description:
        fields["description"] = _clip(strip_html_text(description), max_text_chars)

    return fields


# ── 正文 ─────────────────────────────────────────────────────────────────


def _heuristic_main_text(tree, *, max_chars: int) -> str:
    """确定性正文启发式（trafilatura 缺席时的退路）。

    做法：按候选选择器找容器 → 选**文本最长**的那个（招聘详情页正文总比导航长），
    都找不到就用 body。去掉噪声标签后压空白。

    ⚠️ 本函数会**就地删掉**树上的噪声节点。所以 `extract_page` 必须先跑完 jsonld / og
    两层再来调它 —— 顺序反了会把 `<script type="application/ld+json">` 当噪声删掉，
    结构化字段就全没了。下面 `extract_page` 里的调用顺序是刻意的，别调整。
    """
    for bad in tree.xpath("//" + " | //".join(_NOISE_TAGS)):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)

    candidates: list[str] = []
    for xpath in _CONTENT_XPATHS:
        for node in tree.xpath(xpath):
            candidates.append(_collapse(node.text_content()))

    if not candidates:
        body = tree.find(".//body")
        candidates.append(_collapse(body.text_content() if body is not None else tree.text_content()))

    text = max(candidates, key=len) if candidates else ""
    return _clip(text, max_chars)


def extract_main_text(html: bytes | str, tree, *, max_chars: int, url: str = "") -> str:
    """正文提取：优先 trafilatura（质量高、去噪强），失败/缺席退回启发式。"""
    if trafilatura is not None:
        raw: bytes | str = html if isinstance(html, (bytes, str)) else ""
        try:
            extracted = trafilatura.extract(
                raw,
                url=url or None,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
                output_format="txt",
            )
        except Exception as exc:  # noqa: BLE001 - 第三方库对畸形页面会抛各种异常
            logger.debug("trafilatura 提取失败，改用启发式 | error={}", exc)
            extracted = None
        if extracted and extracted.strip():
            return _clip(_collapse(extracted), max_chars)

    if tree is None:
        return ""
    return _heuristic_main_text(tree, max_chars=max_chars)


# ── 总入口 ───────────────────────────────────────────────────────────────


def extract_page(
    html: bytes | str,
    *,
    url: str = "",
    max_text_chars: int = 4000,
) -> PageFacts:
    """把一页 HTML 抽成 `PageFacts`（字段 + provenance + 正文）。

    字段合并顺序即优先级：jsonld → og。**先到先得**，后到的层级只补前一级缺的键。
    """
    tree = parse_html(html)
    if tree is None:
        return PageFacts(error="HTML 解析失败")

    facts = PageFacts()

    tiers: list[str] = []
    tiers_hit: list[str] = []

    jsonld = extract_jsonld_fields(tree, max_text_chars=max_text_chars)
    if jsonld:
        tiers.append("jsonld")
        tiers_hit.append("jsonld")

    meta = extract_meta_fields(tree, max_text_chars=max_text_chars)
    if meta:
        tiers.append("og")
        tiers_hit.append("og")

    for tier_name, tier_fields in (("jsonld", jsonld), ("og", meta)):
        for key, value in tier_fields.items():
            if value in (None, "", [], {}):
                continue
            if key in facts.fields:
                continue  # 高优先级层级已填
            facts.fields[key] = value
            facts.tier_of[key] = tier_name

    facts.title = facts.fields.get("title")
    facts.text = extract_main_text(html, tree, max_chars=max_text_chars, url=url)

    # text 层只补 description（见模块 docstring 第 2 条）
    if facts.text:
        tiers_hit.append("text")
        if "description" not in facts.fields:
            facts.fields["description"] = _clip(facts.text, max_text_chars)
            facts.tier_of["description"] = "text"

    facts.tiers_hit = tuple(tiers_hit)
    return facts


__all__ = [
    "FIELD_KEYS",
    "PageFacts",
    "extract_jsonld_fields",
    "extract_main_text",
    "extract_meta_fields",
    "extract_page",
    "parse_html",
    "strip_html_text",
]
