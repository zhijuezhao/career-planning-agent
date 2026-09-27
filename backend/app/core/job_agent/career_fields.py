"""从 `job_raw_data` 的自由文本里**确定性**解析「岗位晋升 / 换岗方向 / 所需证书」。

为什么要这个模块（2026-09-27 实测结论）
------------------------------------------------
`#853` 导的是**职业发展路线表**，它的额外列按 `schema_detect.MERGE_RULES` 的**设计**
并进了 `description` / `requirements` 自由文本，指望 portrait 的 LLM 再抽成结构化字段。
但 portrait 对 82 行里约 73 行**静默失败**（`portrait_builder` 的 `except` 返回
`_DEFAULT_PORTRAIT`），于是 `career_path` 全空、`transition_paths` 只 8 条有内容。

而这些内容就是 `A / B / C` 列表 —— **不需要 LLM**，确定性拆分即可。
本模块就是那个拆分器：0 token、可重跑、不依赖模型是否可用。

文本形态（实测 **84/84 行完全一致**）::

    description  = "岗位晋升：全栈工程师 / 技术经理\\n换岗方向：测试开发工程师 / Python / 数据工程师"
    requirements = "核心技能：Java（Java 8+ Stream/Lambda/JUC）、…\\n所需证书：软考（软件设计师/系统架构师）、…"

⚠️ **分隔符按字段不同**：晋升 / 换岗用 ` / `，证书用 `、`。
证书名内部含 `/`（`软考（软件设计师/系统架构师）`），若用 ` / ` 切会把一项切成两项。
"""

from __future__ import annotations

import re

#: 结构化字段 → 源文本里的中文标签
FIELD_LABELS: dict[str, str] = {
    "career_path": "岗位晋升",
    "transition_paths": "换岗方向",
    "certificates": "所需证书",
}

#: 字段 → 列表分隔符（**不能统一**，见模块头说明）
FIELD_SEPARATORS: dict[str, str] = {
    "career_path": "/",
    "transition_paths": "/",
    "certificates": "、",
}

#: 解析结果为空时用来交代"为什么空"的字段名（报告用）
RAW_TEXT_FIELDS: dict[str, str] = {
    "career_path": "description",
    "transition_paths": "description",
    "certificates": "requirements",
}

#: 单项长度上限：超过它基本等于"分隔符没匹配上、把整段当成了一项"
MAX_ITEM_LENGTH = 80


def parse_labelled_list(text: str | None, field: str) -> list[str]:
    """从 ``text`` 里取 ``<标签>：X<分隔符>Y`` 的 X/Y。

    规则：
    - label 只在本**行**内生效（`.` 不跨行）—— 所以 `description` 里
      「岗位晋升」和「换岗方向」各取各的行，不会互相污染；
    - 全角 `：` 与半角 `:` 都认；
    - 逐项 strip，去掉空项与尾部句号；
    - 找不到标签 → 返回 ``[]``（**不抛错**：源文本千奇百怪，静默跳过比炸掉好；
      脚本侧会把"有多少条没解析出来"报出来，不会让失败隐形）。

    Args:
        text: 源自由文本（`description` 或 `requirements`）。
        field: ``FIELD_LABELS`` 里的键之一。

    Raises:
        KeyError: ``field`` 不在 ``FIELD_LABELS`` 里（这是代码 bug，不该静默）。
    """
    label = FIELD_LABELS[field]
    separator = FIELD_SEPARATORS[field]
    if not text:
        return []

    match = re.search(rf"{re.escape(label)}\s*[：:]\s*(.+)", text)
    if match is None:
        return []

    raw = match.group(1)
    items: list[str] = []
    for chunk in raw.split(separator):
        item = chunk.strip().strip("。.;；,，")
        if item:
            items.append(item)
    return items


def extract_career_fields(description: str | None, requirements: str | None) -> dict[str, list[str]]:
    """从两条自由文本里抽出结构化字段。

    Returns:
        只包含**真的抽到内容**的字段（空列表的字段不出现在结果里），
        便于调用方直接 ``profile.career_path = result.get("career_path") or profile.career_path``。
    """
    sources = {"description": description, "requirements": requirements}
    found: dict[str, list[str]] = {}
    for field, source_key in RAW_TEXT_FIELDS.items():
        items = parse_labelled_list(sources.get(source_key), field)
        if items:
            found[field] = items
    return found


def looks_suspicious(items: list[str], field: str) -> bool:
    """解析结果自检：任一项过长（= 分隔符没生效）或仍残留**该字段的另一个**分隔符，都算可疑。

    用于脚本的**事务内自检** —— 避免把"整段当成一项"的脏数据写进库。

    注意只查"另一个"分隔符：`certificates` 的项里合法地含 `/`
    （`软考（软件设计师/系统架构师）`），所以对它只查 ` / `（带空格）。
    """
    other = " / " if FIELD_SEPARATORS.get(field) == "、" else "、"
    for item in items:
        if len(item) > MAX_ITEM_LENGTH:
            return True
        if other in item:
            return True
    return False


__all__ = [
    "FIELD_LABELS",
    "FIELD_SEPARATORS",
    "MAX_ITEM_LENGTH",
    "RAW_TEXT_FIELDS",
    "extract_career_fields",
    "looks_suspicious",
    "parse_labelled_list",
]
