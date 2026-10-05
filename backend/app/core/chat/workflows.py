"""确定型工作流 —— L1 路由命中后执行，**0 token**。

用户对 chat 的定位（§11 原话）："能走工作流就不用 agent，agent 只用于复杂场景下的
决策判断"。所以这里的每个工作流都必须是**纯确定性**的：只查 DB + 套规则，
**绝不调用任何模型**（因此也绝不会因为"没绑 default 模型"而失败）。

契约::

    async def workflow(session: AsyncSession, ctx: WorkflowContext) -> WorkflowResult

- ``text``：给用户看的文字（仍会走输出侧合规，统一追加免责声明）
- ``viz``：``list[dict]``，可为空；契约见 ``app/core/chat/viz.py``

新增工作流：写函数 → 注册进 ``WORKFLOWS`` → 在 ``router.L1_RULES`` 里加规则。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat.viz import bar_option, echarts_viz, table_viz
from app.domain.models.job import JobProfile

#: 「岗位列表」默认给多少条 / 上限（防止一条消息塞进上百行表格）
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass
class WorkflowResult:
    """工作流的产出。"""

    text: str
    viz: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowContext:
    """工作流的运行时入参 —— 工作流**只能**从这里拿参数与身份，别处不许取。"""

    params: dict[str, Any]
    user_id: int


WorkflowFn = Callable[[AsyncSession, WorkflowContext], Awaitable[WorkflowResult]]


# ── 岗位名 → 大类 ────────────────────────────────────────────────────────────
#
# 库里 82 条真实画像的 `industry` / `salary_range` **填充率都是 0**
# （导入源是"职业发展路线表"，压根没有这几列；`company_id` 那一列 2026-09-27 任务 3 已删除），
# 所以任何"按行业/薪资/公司分布"的图都是编的。而按**岗位名**归类是有依据的 ——
# 那 82 个名字本身就是一套岗位分类学。
#
# 顺序即优先级，三条容易踩的：
#   ① `JavaScript` 必须排在 `Java` 前面，否则会被「后端/语言」抢走；
#   ② `游戏测试` / `测试经理` 要落进「测试」，不能落进「前端/游戏」或「项目/管理」；
#   ③ `语音/视频/图形开发` 是媒体开发 —— 所以「算法/AI」的关键词都写成**完整词**
#      （`语音算法` 而不是 `语音`），否则它会被误判成算法岗。
TITLE_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "算法 / AI",
        (
            "算法",
            "机器学习",
            "深度学习",
            "大模型",
            "数据挖掘",
            "自动驾驶",
            "SLAM",
            "自然语言处理",
        ),
    ),
    (
        "数据",
        ("数据开发", "数据仓库", "ETL", "数据架构", "爬虫", "数据采集", "数据治理", "数据标注"),
    ),
    ("测试", ("测试",)),
    (
        "前端 / 客户端 / 游戏",
        ("前端", "JavaScript", "Android", "iOS", "U3D", "UE4", "Cocos", "技术美术", "语音/视频/图形"),
    ),
    (
        "运维 / 网络 / 安全 / 支持",
        ("运维", "IT技术支持", "网络", "安全", "系统", "DBA", "维修", "电脑"),
    ),
    ("项目 / 管理 / 实施", ("项目经理", "项目管理", "实施", "需求分析", "项目专员", "技术经理")),
    ("售前 / 客户", ("售前", "销售技术", "技术支持", "客户成功")),
    ("高管 / 架构", ("架构师", "技术总监", "CTO", "CIO", "技术合伙人")),
    ("文档", ("文档",)),
    (
        "后端 / 语言",
        (
            "Java",
            "C/C++",
            "PHP",
            "Python",
            "C#",
            ".NET",
            "Golang",
            "Node",
            "全栈",
            "后端",
            "区块链",
            "GIS",
            "高性能计算",
        ),
    ),
    # ── 业务岗类目（2026-10-04 补）────────────────────────────────────────────
    # 为什么补：上面的类目是**技术岗视角**，而真实导入的比赛数据（智联招聘 524 行）
    # 以**销售 / 客服 / 运营 / 法务 / 翻译 / 行政**为主 —— 实测 47 个真导入岗位名里
    # **34 个**落进 `其他`（`test_chat_workflows.py::test_every_real_title_is_classified`
    # 就是看住这条的）。落进「其他」意味着学生问"有哪些销售岗"时，岗位分布图会把这些
    # 岗位全塞进一个兜底桶，等于这个模块对真实数据不可用。
    #
    # ⚠️ 顺序即优先级（`classify_title` 第一个命中即返回），所以：
    #   * 这些类目**放在最后** → 技术岗类目保持原优先级，不会把既有归类改掉；
    #   * `客服 / 审核` 排在 `运营 / 市场` 之前，否则"内容审核"会被"内容"抢走；
    #   * `法务` 排在 `人力 / 行政` 之前，否则"律师助理"会被"助理"抢走；
    #   * 故意**不**收录光秃秃的"顾问"，否则"猎头顾问"会被"咨询/顾问"抢走。
    ("客服 / 审核", ("客服", "售后", "呼叫中心", "内容审核", "审核", "客诉")),
    (
        "销售 / BD / 推广",
        ("销售", "BD", "商务拓展", "推广", "地推", "渠道", "大客户", "招商", "门店"),
    ),
    ("法务 / 合规 / 知识产权", ("法务", "律师", "合规", "知识产权", "专利", "商标", "诉讼")),
    ("翻译 / 语言", ("翻译", "译员", "英语", "日语", "韩语", "外贸")),
    ("培训 / 教育", ("培训", "讲师", "教师", "教研", "课程", "助教")),
    ("科研 / 质量 / 统计", ("科研", "研究", "质检", "质量", "统计", "化验", "检测", "试验")),
    ("运营 / 市场", ("运营", "市场", "新媒体", "电商", "编辑", "策划")),
    (
        "人力 / 行政",
        (
            "招聘", "猎头", "人事", "人力", "HR", "行政", "助理", "秘书", "总助",
            "档案", "资料", "管培", "储备干部", "储备经理", "文员", "前台",
        ),
    ),
    ("咨询 / 招投标", ("咨询", "招投标", "投标", "招标", "标书", "造价")),
)

#: 一个关键词都没命中的兜底类目（**应当尽量为 0** —— 见
#: ``test_core/test_chat_workflows.py`` 里"全部 82 条都能归类"的断言）
OTHER_CATEGORY = "其他"


def classify_title(title: str) -> str:
    """把岗位名归进一个大类（第一个命中的关键词决定，**大小写不敏感**）。"""
    lowered = (title or "").lower()
    for category, keywords in TITLE_CATEGORIES:
        for keyword in keywords:
            if keyword.lower() in lowered:
                return category
    return OTHER_CATEGORY


# ── 工作流实现 ───────────────────────────────────────────────────────────────


async def job_catalog(session: AsyncSession, ctx: WorkflowContext) -> WorkflowResult:
    """岗位目录 / 岗位大类分布 —— 全部基于 ``job_profiles`` 的**岗位名**。

    ``params``：
        - ``mode``：``"list"``（默认，给表格）或 ``"distribution"``（给柱状图）
        - ``limit``：``list`` 模式下的条数（1..``MAX_LIST_LIMIT``）
    """
    mode = str(ctx.params.get("mode") or "list")

    total = (await session.execute(select(func.count()).select_from(JobProfile))).scalar() or 0
    if total == 0:
        return WorkflowResult(text="库里目前还没有岗位数据，等导入完成后我再帮你统计。")

    if mode == "distribution":
        titles = (await session.execute(select(JobProfile.title))).scalars().all()
        counts: dict[str, int] = {}
        for title in titles:
            category = classify_title(title)
            counts[category] = counts.get(category, 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

        top = "、".join(f"{name}（{count}）" for name, count in ordered[:3])
        text = (
            f"库里目前有 {total} 个岗位，按岗位名可以归成 {len(ordered)} 个大类。\n"
            f"数量最多的三类是：{top}。\n"
            "下面是完整分布（按数量从多到少）。"
        )
        viz = [
            echarts_viz(
                "bar",
                "岗位大类分布",
                bar_option(
                    [name for name, _ in ordered],
                    [count for _, count in ordered],
                    series_name="岗位数",
                ),
            )
        ]
        return WorkflowResult(text=text, viz=viz)

    limit = _clamp_limit(ctx.params.get("limit"))
    titles = (
        (await session.execute(select(JobProfile.title).order_by(JobProfile.id).limit(limit)))
        .scalars()
        .all()
    )
    shown = len(titles)
    more = "" if shown >= total else f"（共 {total} 个，这里只列出前 {shown} 个）"
    text = f"库里目前有 {total} 个岗位，下面按入库顺序列出前 {shown} 个。{more}".strip()
    return WorkflowResult(
        text=text,
        viz=[table_viz("岗位列表", ["#", "岗位名称"], [[i + 1, t] for i, t in enumerate(titles)])],
    )


def _clamp_limit(raw: Any) -> int:
    """把工作流入参里的 ``limit`` 收敛成合法整数（脏输入不抛错，退回默认值）。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIST_LIMIT
    return max(1, min(value, MAX_LIST_LIMIT))


#: 工作流注册表：``路由规则里的 workflow 名`` → 实现
WORKFLOWS: dict[str, WorkflowFn] = {
    "job_catalog": job_catalog,
}


async def run_workflow(name: str, session: AsyncSession, ctx: WorkflowContext) -> WorkflowResult:
    """按名字跑一个工作流（名字不存在直接抛 —— 那是代码 bug，不该被静默吞掉）。"""
    workflow = WORKFLOWS.get(name)
    if workflow is None:
        raise KeyError(f"未注册的工作流：{name!r}（已注册：{sorted(WORKFLOWS)}）")
    return await workflow(session, ctx)


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "OTHER_CATEGORY",
    "TITLE_CATEGORIES",
    "WORKFLOWS",
    "WorkflowContext",
    "WorkflowResult",
    "classify_title",
    "job_catalog",
    "run_workflow",
]
