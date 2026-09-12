"""Golden test set for RAG accuracy regression testing.

Each test case consists of a query, a list of expected hit titles,
and optional category filter. The test runner seeds the knowledge
base with controlled vectors and verifies that the retriever returns
the expected results.

Usage:
    pytest tests/test_core/test_rag_accuracy.py -v
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoldenTestCase:
    """A single RAG accuracy test case.

    Attributes:
        query: The search query text.
        expected_titles: Titles that MUST appear in the top-K results.
        category: Optional category filter to apply.
        query_seed: Vector seed for the mock query embedding (matching
                    the expected entry's vector).
        description: Human-readable description of what this tests.
        min_top_k: Minimum rank the expected results should appear in.
    """

    query: str
    expected_titles: list[str] = field(default_factory=list)
    category: str | None = None
    query_seed: float = 0.0
    description: str = ""
    min_top_k: int = 5


# All knowledge entries that will be seeded into the test DB.
# Each entry has a unique vector seed for deterministic distance ordering.
GOLDEN_KNOWLEDGE_ENTRIES: list[dict] = [
    {
        "title": "前端开发技能要求",
        "content": "前端开发需要掌握HTML、CSS、JavaScript三大基础技术，"
        "以及Vue.js、React等主流框架，还需要了解Webpack等构建工具"
        "和基本的浏览器兼容性知识。",
        "category": "skill",
        "seed": 0.10,
    },
    {
        "title": "后端开发技能要求",
        "content": "后端开发需要掌握Python、Java、Go等编程语言，"
        "熟悉MySQL、PostgreSQL等数据库，了解Linux系统运维和"
        "RESTful API设计规范。",
        "category": "skill",
        "seed": 0.20,
    },
    {
        "title": "数据分析师技能要求",
        "content": "数据分析师需要掌握SQL进行数据查询，Python进行数据处理，"
        "统计学知识进行假设检验，以及Tableau等数据可视化工具。",
        "category": "skill",
        "seed": 0.30,
    },
    {
        "title": "产品经理岗位要求",
        "content": "产品经理需要具备市场分析能力、用户需求调研能力、"
        "产品原型设计能力（Axure/Figma）、项目管理能力和数据分析能力。",
        "category": "job",
        "seed": 0.40,
    },
    {
        "title": "UI设计师岗位要求",
        "content": "UI设计师需要掌握Figma、Sketch等设计工具，了解设计系统搭建、"
        "用户研究方法和交互设计原则，具备良好的视觉审美能力。",
        "category": "job",
        "seed": 0.50,
    },
    {
        "title": "IT行业发展趋势",
        "content": "IT行业正朝着人工智能、云计算、大数据、物联网方向快速发展，"
        "企业对全栈工程师和AI工程师的需求持续增长。",
        "category": "career",
        "seed": 0.60,
    },
    {
        "title": "金融行业发展趋势",
        "content": "金融科技、数字人民币、绿色金融和智能风控是金融行业"
        "的新趋势，传统金融机构正在加速数字化转型。",
        "category": "career",
        "seed": 0.70,
    },
    {
        "title": "医疗行业发展趋势",
        "content": "医疗行业数字化、远程医疗服务、AI辅助诊断和精准医疗"
        "是当前医疗行业的主要发展方向。",
        "category": "career",
        "seed": 0.80,
    },
]


# Golden test cases: each query vector is set to match the expected entry.
# query_seed should be close to the expected entry's seed.
GOLDEN_TEST_CASES: list[GoldenTestCase] = [
    GoldenTestCase(
        query="前端开发需要学什么",
        expected_titles=["前端开发技能要求"],
        query_seed=0.10,
        description="检索前端开发技能",
    ),
    GoldenTestCase(
        query="后端编程语言",
        expected_titles=["后端开发技能要求"],
        query_seed=0.20,
        description="检索后端开发技能",
    ),
    GoldenTestCase(
        query="数据分析SQL技能",
        expected_titles=["数据分析师技能要求"],
        query_seed=0.30,
        description="检索数据分析技能",
    ),
    GoldenTestCase(
        query="产品经理工作内容",
        expected_titles=["产品经理岗位要求"],
        query_seed=0.40,
        description="检索产品经理岗位",
    ),
    GoldenTestCase(
        query="UI设计工具",
        expected_titles=["UI设计师岗位要求"],
        query_seed=0.50,
        description="检索UI设计师岗位",
    ),
    GoldenTestCase(
        query="IT行业前景",
        expected_titles=["IT行业发展趋势"],
        query_seed=0.60,
        description="检索IT行业趋势",
    ),
    GoldenTestCase(
        query="金融科技趋势",
        expected_titles=["金融行业发展趋势"],
        query_seed=0.70,
        description="检索金融行业趋势",
    ),
    GoldenTestCase(
        query="医疗数字化",
        expected_titles=["医疗行业发展趋势"],
        query_seed=0.80,
        description="检索医疗行业趋势",
    ),
    GoldenTestCase(
        query="编程技能分类",
        expected_titles=["前端开发技能要求", "后端开发技能要求", "数据分析师技能要求"],
        category="skill",
        query_seed=0.15,
        description="按skill类别过滤，应返回所有技能类条目",
        min_top_k=5,
    ),
    GoldenTestCase(
        query="岗位信息",
        expected_titles=["产品经理岗位要求", "UI设计师岗位要求"],
        category="job",
        query_seed=0.45,
        description="按job类别过滤，应返回所有岗位类条目",
        min_top_k=5,
    ),
    GoldenTestCase(
        query="行业趋势分析",
        expected_titles=["IT行业发展趋势", "金融行业发展趋势", "医疗行业发展趋势"],
        category="career",
        query_seed=0.70,
        description="按career类别过滤，应返回所有行业趋势类条目",
        min_top_k=5,
    ),
]

# Seed for the "noise" entries that should not match any query
NOISE_SEED = 0.99
