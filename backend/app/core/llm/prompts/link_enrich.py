"""链接字段解析（L3）的提示词。

设计意图 —— **让模型"挑"而不是"编"**（主计划 §4.2 第 2、3 点）：

- 输入是**候选 XPath 菜单**（每项都已在本文档上验证可解析，并附它当前取到的文本）
  + 可见正文截断。**绝不把整页 HTML 喂模型** —— 导航/广告/推荐位白吃 token 就是
  "数据污染"；
- 输出要求模型**从菜单里选**定位式，并给出它读到的值；
- 菜单之外自己编的表达式会被后置校验拒绝（`xpath.validate_xpath` + 实际解析验证），
  所以"编"没有收益。

## 与"不编造数据"的关系

提示词明确要求"读不到就返回 null，不要猜"，并且**后置校验不信任模型抄的值**：
真正采用的是"用模型给的 XPath 在本页取到的文本"。模型把值抄错、或者凭想象填一个
页面上根本没有的值，都会在校验环节被发现（取不到 → 该字段丢弃）。
这条是针对本项目反复强调的"不要编数据"的硬约束，而不只是提示词里的一句叮嘱。

`{candidates}` / `{text}` 用 `.replace()` 注入而不是 `.format()`：
正文里可能出现任意花括号（JSON 片段、代码块），`format` 会直接抛 KeyError。
"""

from __future__ import annotations

import json

_SYSTEM_PROMPT = """你是一个招聘网页字段抽取器。
任务：在给定的候选中，为每个字段挑出最合适的定位式（XPath），并读出它的值。

铁律：
1. **只能从候选列表里挑 XPath**，不要自己编写表达式。候选之外的一律不用。
2. **读不到就返回 null**。绝对不要猜测、不要用常识补全、不要编造页面上没有的值。
3. `company` 必须是**招聘公司**。站点名（如"BOSS直聘""智联招聘"）不是公司名 ——
   若页面上只有站点名而没有招聘方，`company` 返回 null。
4. 值必须是**页面上真实存在的文本**（可以去掉首尾空白），不要改写、不要翻译、不要归一化。
5. 同一字段有多个候选时，选**匹配数最少、语义最贴**的那个（越具体的定位式越稳定）。

输出严格 JSON（不要加解释、不要加 markdown 代码块）：
{"fields": {"<字段名>": {"value": "<页面上的原文>", "xpath": "<候选里的 XPath>"}, ...}}
没有把握的字段直接不出现（或值为 null）。"""

_USER_TEMPLATE = """域名：{domain}

需要抽取的字段：{fields}

候选定位式（只能在其中挑选）：
{candidates}

页面可见正文（截断，仅用于判断候选对不对）：
---
{text}
---

按要求只输出 JSON。"""


def build_link_extract_messages(
    *,
    domain: str,
    fields: list[str],
    candidates: list[dict],
    text: str,
) -> list[dict[str, str]]:
    """构造 L3 调用的消息列表（OpenAI 风格 dict，网关直接吃）。

    `candidates` 的每一项形如 `{"field": ..., "xpath": ..., "preview": ...}`
    （由 `xpath.Candidate.as_prompt_item()` 产出）。
    """
    menu = json.dumps(candidates, ensure_ascii=False, indent=1)
    user = (
        _USER_TEMPLATE.replace("{domain}", domain or "(未知)")
        .replace("{fields}", "、".join(fields))
        .replace("{candidates}", menu)
        .replace("{text}", text or "(空)")
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


__all__ = ["build_link_extract_messages"]
