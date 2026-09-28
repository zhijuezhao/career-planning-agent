"""候选 XPath 的生成、**安全校验**与应用（B3-2 的 L2/L3 共用）。

## 两个方向的数据流

- **生成（本地规则，零 LLM）**：`build_xpath_candidates()` 扫 DOM，产出"可能承载某个
  字段"的候选定位式 + 文本预览。给模型当菜单，让它**挑**而不是**编** ——
  这是 §4.2 第 3 点"让模型输出 XPath"能落地的前提：菜单里的每一项都已验证可解析，
  模型选错的代价被限制在"选到别的字段"而不是"给出一堆跑不通的表达式"。
- **执行（模型产出）**：`apply_xpath()` 只执行**通过 `validate_xpath()` 白名单**的表达式。

## 为什么必须校验模型产出的 XPath

XPath 本身不能执行代码（lxml 里没有 `eval`），所以风险不是 RCE 而是 **DoS**：
一条 `//*[contains(., 'a')]` 在 2MB 文档上会退化成对整个文档做子串匹配，
再叠加嵌套谓词就更糟。所以校验采取**白名单语法**（而不是黑名单）：

- 只允许 `//` 开头的**简单路径**（`//tag[pred]` / `//*[@attr="literal"]`）；
- 函数只允许 `contains` / `normalize-space` / `concat` / `text` / `starts-with` 等
  文本处理函数；
- **禁止轴（`::`）、联合（`|`）、`document()`、`@*`**；
- 限制长度、谓词个数与 `//` 段数。

配套的第二道闸门是文档大小：抓取层已经把响应体卡在 `LINK_ENRICH_MAX_BYTES`（2MB），
所以"表达式复杂度 × 文档大小"两边都有界。

## 为什么只生成 id/class/name 型定位式

绝对路径（`/html/body/div[3]/div[2]/span`）在同一站点的**第二页**必然失效 ——
而 L2 的全部价值就是"同域复用"。所以 `stable_xpath_for()` 只产**语义锚点**：
有 `id` 用 `//*[@id=...]`，有 class 用 `contains(@class, "...")`，有 `name` 用 `@name`。
没有锚点的元素**直接放弃**（宁可不给候选，也不给一个下次一定失效的定位式）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from loguru import logger

#: 执行/生成本模块表达式时的结果上限（再多的匹配对"取一个字段值"也没有意义）
MAX_MATCHES = 5

#: 允许在模型产出的 XPath 里出现的函数（其余一律拒绝）
ALLOWED_FUNCTIONS = frozenset(
    {
        "contains",
        "normalize-space",
        "concat",
        "starts-with",
        "string-length",
        "substring-before",
        "substring-after",
        "translate",
        "text",
    }
)

MAX_XPATH_LENGTH = 240
MAX_PREDICATES = 4
MAX_DOUBLE_SLASH = 3

#: 允许出现的字符：XPath 语法字符 + 字母数字 + 中日韩文字与常见中文标点（用于字符串字面量）。
#: ⚠️ **逗号必须在列**：XPath 1.0 的函数参数分隔用半角逗号，而
#: `//a[contains(concat(" ", normalize-space(@class), " "), 'x')]` 是本模块**自己生成**的
#: 主力形状 —— 漏掉逗号会让自己的表达式过不了自己的校验（表现为"候选永远为空"，
#: 而且不报错，只是静默没有候选；2026-09-27 自查抓到）。`test_link_enrich_xpath.py`
#: 里有一条用例专门断言"本模块生成的表达式必须通过本模块的校验"。
_ALLOWED_CHARS_RE = re.compile(
    r"^[A-Za-z0-9_\-@\[\]=\"',\*\/\.\(\)\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+$"
)

#: 被明确禁掉的构造（给出可读原因，便于排查"模型为什么被拒"）
_FORBIDDEN = (
    ("::", "不允许轴（::）"),
    ("|", "不允许联合（|）"),
    ("document(", "不允许 document()"),
    ("@*", "不允许 @*"),
    ("..", "不允许父节点（..）"),
)

_FUNC_CALL_RE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)\s*\(")

#: `contains(., "...")` 的性能陷阱**只对 `//*` 成立**：
#: `//*[contains(., 'x')]` 会把文档里每个元素的后代文本都拼出来比对一遍；
#: 而 `//li[contains(., '薪资')]` 只对 `li` 节点求值，是完全正常的用法 ——
#: 而且它正是"标签-值"结构唯一**轴无关**的表达方式（见 `_pair_locator`）。
#: 所以判定收紧为：**出现 `//*` 且出现 `contains(.,` 才拒绝**。
_FULL_NODE_CONTAINS_RE = re.compile(r"contains\s*\(\s*\.")


def _has_wildcard_contains(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return "//*" in compact and "contains(.," in compact

#: 字段 → 关键词（中英文）。命中 class/id/name/itemprop/tag 或**自身文本**都算。
FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "company": ("公司", "企业", "招聘单位", "用人单位", "company", "employer", "organization", "org"),
    "city": ("城市", "地点", "工作地", "所在地", "地址", "city", "location", "address", "region"),
    "region": ("省份", "地区", "城市", "region", "province", "state"),
    "salary": ("薪", "工资", "待遇", "报酬", "salary", "pay", "compensation", "wage"),
    "industry": ("行业", "领域", "industry", "sector", "category"),
    "level": ("级别", "职级", "层级", "level", "grade", "seniority"),
    "education_requirement": ("学历", "学位", "education", "degree", "qualification"),
    "experience_requirement": ("经验", "年限", "工作经历", "experience", "seniority", "years"),
}

#: 交给模型的字段集合。
#: **刻意不含 `description` / `requirements`**：这两个由 L1 的正文提取（trafilatura）
#: 负责，长文本用一条 XPath 重新定位的收益低、失效概率高；短结构化字段才是
#: "换一页还想再取到同一个值"的东西。
EXTRACTABLE_FIELDS: tuple[str, ...] = (
    "company",
    "city",
    "region",
    "salary",
    "industry",
    "level",
    "education_requirement",
    "experience_requirement",
)

#: 扫描 DOM 的元素数上限（防病态页面把候选生成拖成分钟级）
MAX_SCANNED_ELEMENTS = 20000


@dataclass(frozen=True)
class Candidate:
    """一个候选定位式。`preview` 是它当前取到的文本（给模型判断用）。"""

    field: str
    xpath: str
    preview: str
    score: int
    matches: int

    def as_prompt_item(self) -> dict[str, Any]:
        return {"field": self.field, "xpath": self.xpath, "preview": self.preview[:120]}


# ── 校验 ─────────────────────────────────────────────────────────────────


def validate_xpath(expr: str | None) -> str | None:
    """校验模型产出的 XPath；通过返回 `None`，拒绝返回原因（可读中文）。

    白名单语法，见模块 docstring。**只做静态检查**（不解析文档），
    因此可以在执行前无成本地拒绝掉绝大多数危险/畸形表达式。
    """
    if not expr or not isinstance(expr, str):
        return "空表达式"
    text = expr.strip()
    if not text:
        return "空表达式"
    if len(text) > MAX_XPATH_LENGTH:
        return f"表达式过长（>{MAX_XPATH_LENGTH} 字符）"
    if not text.startswith("//"):
        return "必须以 // 开头（只接受相对全文档的简单路径）"
    if text.count("//") > MAX_DOUBLE_SLASH:
        return f"// 段数过多（>{MAX_DOUBLE_SLASH}）"
    if text.count("[") > MAX_PREDICATES or text.count("[") != text.count("]"):
        return f"谓词过多或括号不配对（>{MAX_PREDICATES}）"

    for token, reason in _FORBIDDEN:
        if token in text:
            return reason

    if _has_wildcard_contains(text):
        return "禁止 //*[contains(., …)] 这种全节点子串匹配（性能陷阱），请用具体标签或 class/id 定位"

    if not _ALLOWED_CHARS_RE.match(text):
        return "包含不允许的字符"

    for name in _FUNC_CALL_RE.findall(text):
        if name.lower() not in ALLOWED_FUNCTIONS:
            return f"不允许的函数：{name}()"
    return None


def _xpath_literal(value: str) -> str | None:
    """把值安全地放进 XPath 字符串字面量。

    XPath 1.0 **没有转义机制**，含引号的值只能用 `concat()` 拼（本模块不做这么复杂
    的事）—— 直接放弃这种候选：真实页面的 id/class 里出现引号极其罕见，
    为它引入 concat 拼接不值得。含双引号与单引号的一律 `None`。
    """
    if not value or '"' in value or "'" in value:
        return None
    if any(ch in value for ch in "<>&"):
        return None
    return f'"{value}"'


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _safe_literal(value: str) -> str | None:
    """本模块自己生成的 XPath 用：中文值放进**单引号**字面量（不必过模型校验那条路）。"""
    if not value or "'" in value or '"' in value or "<" in value or ">" in value:
        return None
    return f"'{value}'"


# ── 应用 ─────────────────────────────────────────────────────────────────


def _node_text(node: Any) -> str:
    """节点 → 文本。元素取全部后代文本；属性/字符串直接 str()。"""
    try:
        if hasattr(node, "text_content"):
            return " ".join(node.text_content().split())
        return " ".join(str(node).split())
    except Exception:  # noqa: BLE001 - 取文本失败不该让整页失败
        return ""


def apply_xpath(tree: Any, expr: str, *, limit: int = MAX_MATCHES) -> list[str]:
    """执行 XPath 并返回非空文本列表（**先过白名单**）。

    任何异常都吞掉并返回空列表 —— 一条模板跑不通只该记一次 miss，
    不该让整页/整单失败。
    """
    if tree is None:
        return []
    reason = validate_xpath(expr)
    if reason:
        logger.warning("拒绝执行未通过校验的 XPath | reason={} | xpath={:.80}", reason, expr)
        return []
    try:
        nodes = tree.xpath(expr)
    except Exception as exc:  # noqa: BLE001 - lxml 对畸形表达式抛各种异常
        logger.debug("XPath 执行失败 | xpath={:.80} | error={}", expr, exc)
        return []
    if not isinstance(nodes, list):
        nodes = [nodes]

    out: list[str] = []
    for node in nodes[: max(1, limit)]:
        text = _node_text(node)
        if text:
            out.append(text)
    return out


# ── 生成 ─────────────────────────────────────────────────────────────────


def stable_xpath_for(element: Any, tree: Any) -> str | None:
    """为一个元素生成**站点内可复用**的定位式（id > class > name，都没有则放弃）。"""
    tag = element.tag if isinstance(element.tag, str) else ""
    if not tag:
        return None

    element_id = (element.get("id") or "").strip()
    if element_id:
        literal = _safe_literal(element_id)
        if literal:
            return f"//*[@id={literal}]"

    for attr in ("class", "name", "itemprop"):
        raw = (element.get(attr) or "").strip()
        if not raw:
            continue
        if attr == "class":
            # 取**最长**的词：class 里往往是 "job-salary salary-value"，
            # 越长的词越具体、越不容易在别的字段上重复出现
            tokens = sorted({t for t in raw.split() if t}, key=len, reverse=True)
            for token in tokens[:2]:
                literal = _safe_literal(token)
                if not literal:
                    continue
                expr = f'//{tag}[contains(concat(" ", normalize-space(@class), " "), {literal})]'
                if _is_usable(tree, expr):
                    return expr
            continue
        literal = _safe_literal(raw)
        if literal:
            expr = f"//{tag}[@{attr}={literal}]"
            if _is_usable(tree, expr):
                return expr
    return None


def _is_usable(tree: Any, expr: str, *, max_matches: int = 20) -> bool:
    """表达式在本文档上能解析、且匹配数不至于"命中半个页面"。"""
    try:
        nodes = tree.xpath(expr)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(nodes, list) and 0 < len(nodes) <= max_matches


def _value_predicate(element: Any) -> str | None:
    """值元素的唯一化谓词：class 词 > name/itemprop > 无。"""
    tokens = sorted({t for t in (element.get("class") or "").split() if t}, key=len, reverse=True)
    for token in tokens[:1]:
        literal = _safe_literal(token)
        if literal:
            return f'[contains(concat(" ", normalize-space(@class), " "), {literal})]'
    for attr in ("name", "itemprop"):
        raw = (element.get(attr) or "").strip()
        if raw:
            literal = _safe_literal(raw)
            if literal:
                return f"[@{attr}={literal}]"
    return ""


def _pair_locator(tree: Any, label: Any, value: Any, label_text: str) -> str | None:
    """为「标签-值」结构生成**语义配对**定位式（轴无关）。

    形状：`//li[contains(., '薪资')]/span[...]` —— 先按标签文字锚定到那一行，
    再取行内的值元素。

    为什么必须有它：中文岗位页大量写作
    `<li><span class="p-label">薪资</span><span class="p-value">25-40K</span></li>`，
    而 `p-value` 这个 class 在整页**匹配 5 个元素**（薪资/城市/经验/学历/行业各一个）。
    如果只给"按 class 定位"的候选，模型选出来的模板就是**取第一个匹配**——
    在本文档碰巧对，换一页顺序一变就**静默取错值**。配对定位式把"哪一个值"说清楚。

    ⚠️ 只有**验证过唯一**（恰好 1 个匹配）才返回 —— 多匹配的配对定位式同样会
    静默取错，宁可不给候选。
    """
    parent = label.getparent()
    if parent is None or not isinstance(parent.tag, str) or not label_text:
        return None
    label_literal = _safe_literal(label_text)
    if not label_literal:
        return None
    predicate = _value_predicate(value)
    if predicate is None:
        return None
    expr = f"//{parent.tag}[contains(., {label_literal})]/{value.tag}{predicate}"
    return expr if _is_usable(tree, expr, max_matches=1) else None


def _signals(element: Any) -> str:
    """把"这个元素像不像某个字段"的证据拼成一个串（class/id/name/itemprop/tag）。"""
    parts: list[str] = []
    for attr in ("id", "class", "name", "itemprop", "data-role", "data-testid"):
        value = element.get(attr)
        if value:
            parts.append(str(value))
    if isinstance(element.tag, str):
        parts.append(element.tag)
    return " ".join(parts).lower()


def _score(field: str, signals: str, own_text: str) -> int:
    """打分：属性命中 > 自身文本命中 > 只是"关键词的兄弟节点"。"""
    score = 0
    lowered_text = own_text.lower()
    for keyword in FIELD_KEYWORDS.get(field, ()):
        low = keyword.lower()
        if low in signals:
            score += 3
        if low in lowered_text and len(own_text) <= 40:
            # 自身文本就是"薪资"这类标签（而不是一整段正文）时才加分
            score += 2
    return score


def build_xpath_candidates(
    tree: Any,
    fields: Iterable[str] = EXTRACTABLE_FIELDS,
    *,
    per_field_limit: int = 4,
    total_limit: int = 40,
) -> list[Candidate]:
    """扫 DOM 产出候选定位式（零 LLM，已在本文档上验证可解析）。

    关键词直接命中之外，还刻意加了一条**"标签-值"规则**：招聘页大量写作
    `<div class="label">薪资</div><div class="value">20-30K</div>` —— 值所在的
    `div` 本身没有任何"薪资"字样，只靠关键词永远找不到它。所以当某元素的自身文本
    命中关键词时，把它的**下一个兄弟元素**也作为该字段的候选（并标更低的分）。
    """
    if tree is None:
        return []

    wanted = [f for f in fields if f in FIELD_KEYWORDS]
    if not wanted:
        return []

    buckets: dict[str, list[Candidate]] = {field: [] for field in wanted}
    seen: dict[str, set[str]] = {field: set() for field in wanted}

    def _record(field: str, expr: str, score: int) -> None:
        if score <= 0 or len(buckets[field]) >= per_field_limit * 3:
            return
        if not expr or expr in seen[field]:
            return
        if validate_xpath(expr):
            return
        values = apply_xpath(tree, expr, limit=1)
        if not values:
            return
        try:
            matches = len(tree.xpath(expr))
        except Exception:  # noqa: BLE001
            matches = 1
        seen[field].add(expr)
        buckets[field].append(
            Candidate(field=field, xpath=expr, preview=values[0], score=score, matches=matches)
        )

    def _offer(field: str, element: Any, score: int) -> None:
        expr = stable_xpath_for(element, tree)
        if expr:
            _record(field, expr, score)

    scanned = 0
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue  # 注释 / 处理指令
        scanned += 1
        if scanned > MAX_SCANNED_ELEMENTS:
            logger.warning("候选生成：元素数超过 {} 上限，提前停止", MAX_SCANNED_ELEMENTS)
            break

        signals = _signals(element)
        own_text = " ".join((element.text or "").split())

        for field in wanted:
            score = _score(field, signals, own_text)
            if score > 0:
                _offer(field, element, score + 1)
            # "标签-值"规则与"自身命中"**无关**，两者都要试：
            # `<span class="label">行业</span><span class="value">互联网</span>` 里，
            # 标签元素自己就命中关键词（own_text="行业"），如果这时 `continue`，
            # 真正想要的值元素就永远进不了候选（2026-09-27 实测踩到）。
            if own_text and len(own_text) <= 12:
                for keyword in FIELD_KEYWORDS[field]:
                    if keyword.lower() in own_text.lower():
                        sibling = element.getnext()
                        if sibling is not None and isinstance(sibling.tag, str):
                            # 配对定位式给最高分：它能说清"哪一个值"，
                            # 而只按 class 定位的候选在多行同 class 时是**取第一个**
                            pair = _pair_locator(tree, element, sibling, own_text)
                            if pair:
                                _record(field, pair, score + 5)
                            _offer(field, sibling, score + 3)
                        break

    candidates: list[Candidate] = []
    for field in wanted:
        items = sorted(buckets[field], key=lambda c: (-c.score, c.matches, len(c.preview)))
        candidates.extend(items[:per_field_limit])

    if len(candidates) > total_limit:
        candidates = candidates[:total_limit]
    return candidates


def candidates_by_field(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    """按字段分组（prompt 与测试都用得上）。"""
    grouped: dict[str, list[Candidate]] = {}
    for item in candidates:
        grouped.setdefault(item.field, []).append(item)
    return grouped


__all__ = [
    "ALLOWED_FUNCTIONS",
    "Candidate",
    "EXTRACTABLE_FIELDS",
    "FIELD_KEYWORDS",
    "MAX_MATCHES",
    "apply_xpath",
    "build_xpath_candidates",
    "candidates_by_field",
    "stable_xpath_for",
    "validate_xpath",
]
