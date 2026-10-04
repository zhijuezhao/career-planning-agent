"""技能归一化（B5，2026-10-03 用户拍板「技能只提取最重要的部分」）。

用户原话与选择::

    技能只提取最重要的部分，如 java开发，java，只要 java

→ **仅形态归约**（把带修饰的技能串归约到最基础的技术名词），
  外加数量上限：核心技能 ≤20、加分技能 ≤10。

为什么不直接"剥后缀"（`去掉 开发/框架/数据库`）
------------------------------------------------

机械剥后缀会大面积误伤：`数据分析` 去掉 `分析`？`C/C++` 变成 `C`？
`Node.js` 变成 `Node`？都错。所以本模块用**受控词表 + 最长匹配**：

1. **词表**里放的是"最基础的技术名词"（`Java`/`MySQL`/`Spring Boot`/`C/C++`…）；
2. 在一串技能里找**最长的已知词**；
3. 只有当它**左右剩下的部分全是修饰词**时才归约 ——
   `Java开发` 命中 `Java`，左边空、右边 `开发`（修饰词）→ 归约成 `Java`；
   但 `项目管理工具` 的右边是 `工具`（**不在**修饰词表里，它是实义中心语）→ **不归约**；
4. 没命中词表的，**原样保留**（宁可不归约，也不要瞎猜），并可由
   `unmapped_skills()` 汇总出来供人工补词表。

⚠️ 拉丁词必须做**词边界**匹配，否则 `Go` 会命中 `Google`、`Java` 会命中 `JavaScript`。
"""

from __future__ import annotations

import re

__all__ = [
    "CORE_SKILL_LIMIT",
    "BONUS_SKILL_LIMIT",
    "TECH_VOCABULARY",
    "match_skill_overlap",
    "normalise_skill",
    "normalise_skills",
    "unmapped_skills",
]

#: 核心技能上限（用户 2026-10-03：核心 ≤20）
CORE_SKILL_LIMIT = 20
#: 加分技能上限（用户 2026-10-03：加分 ≤10）
BONUS_SKILL_LIMIT = 10

#: 可出现在技能串里、但**本身不是技能**的修饰词（前缀与后缀）
#:
#: ⚠️ 刻意**不含** `工具`/`系统`/`平台`/`分析`：它们是实义中心语，
#: `项目管理工具` 与 `项目管理` 是两个不同的技能，归约掉就丢信息了。
_SKILL_MODIFIERS: frozenset[str] = frozenset(
    {
        # 前缀（动词/程度）
        "熟悉", "熟练掌握", "熟练", "掌握", "精通", "了解", "具备", "会", "使用",
        "有一定", "良好的", "较强的", "良好的", "相关", "基本的", "扎实的",
        # 后缀（把技术名词包起来的壳）
        "开发", "编程", "程序设计", "语言", "框架", "数据库", "缓存", "中间件",
        "技术", "技术栈", "技能", "能力", "经验", "应用", "基础", "知识",
        "相关技术", "相关经验", "等", "方向", "优先",
        # 部署/运行形态（`Docker容器`→Docker、`K8s集群`→Kubernetes、`Linux环境`→Linux）
        "容器", "集群", "环境",
    }
)

#: 归属化名：同一件事的不同写法 → 词表里的规范名
_SKILL_ALIASES: dict[str, str] = {}


def _register(canonical: str, *aliases: str) -> None:
    _SKILL_ALIASES[canonical.lower()] = canonical
    for alias in aliases:
        _SKILL_ALIASES[alias.lower()] = canonical


# ── 词表：最基础的技术名词 ────────────────────────────────────────────────────
# 组织方式：每个规范名 + 常见别名（连字符/无空格/大小写变体）。
# 覆盖顺序无关（匹配时按长度从长到短排）。
_register("Java", "java开发", "java语言", "java编程")
_register("Python", "python开发", "python语言", "py")
_register("Go", "golang", "go语言")
_register("C", "c语言")
_register("C++", "c++开发", "cpp")
_register("C#", "csharp", "c#开发")
_register("C/C++", "c/c++开发")
_register("JavaScript", "js", "javascript开发", "es6", "ecmascript")
_register("TypeScript", "ts")
_register("PHP", "php开发")
_register("Ruby", "ruby on rails", "rails")
_register("Swift", "swift开发")
_register("Kotlin")
_register("Scala")
_register("R", "r语言")
_register("MATLAB", "matlab")
_register("SQL", "sql语言")
_register("Shell", "shell脚本", "bash")
_register("Objective-C", "oc")
_register("Dart")
_register("Rust")
_register("Perl")
_register("Lua")
_register("Groovy")
_register("HTML", "html5", "html/css")
_register("CSS", "css3", "less", "sass", "scss")
_register("Node.js", "nodejs", "node")
_register("Vue", "vue.js", "vuejs", "vue2", "vue3")
_register("React", "react.js", "reactjs")
_register("Next.js", "nextjs")
_register("Angular", "angularjs")
_register("jQuery", "jquery")
_register("Bootstrap")
_register("Element UI", "elementui", "element-plus")
_register("Ant Design", "antd")
_register("ECharts", "echarts")
_register("Webpack")
_register("Vite")
_register(".NET", "dotnet", "asp.net", "net core", "aspnet")
_register("Spring Boot", "springboot", "spring-boot", "springboot框架")
_register("Spring Cloud", "springcloud", "spring-cloud")
_register("Spring MVC", "springmvc", "spring-mvc")
_register("Spring", "spring框架")
_register("MyBatis", "mybatis-plus", "ibatis")
_register("Hibernate", "jpa")
_register("Django")
_register("Flask")
_register("FastAPI", "fastapi")
_register("Tornado")
_register("Express", "express.js")
_register("Koa")
_register("MySQL", "mysql数据库", "mariadb")
_register("PostgreSQL", "postgres", "pgsql")
_register("Oracle", "oracle数据库")
_register("SQL Server", "sqlserver", "mssql")
_register("SQLite")
_register("Redis", "redis缓存")
_register("MongoDB", "mongo")
_register("Elasticsearch", "es", "elastic search")
_register("Kafka", "apache kafka")
_register("RabbitMQ", "rabbitmq")
_register("RocketMQ", "rocketmq")
_register("Zookeeper", "zookeeper")
_register("HBase", "hbase")
_register("Hive", "hive")
_register("Spark", "spark")
_register("Flink", "flink")
_register("Hadoop", "hadoop")
_register("ClickHouse", "clickhouse")
_register("TiDB", "tidb")
_register("Memcached", "memcache")
_register("Nginx", "nginx")
_register("Tomcat", "tomcat")
_register("Docker", "docker容器")
_register("Kubernetes", "k8s", "k8s集群")
_register("Jenkins", "jenkins")
_register("Git", "git版本控制", "github", "gitlab")
_register("SVN")
_register("Maven", "maven")
_register("Gradle", "gradle")
_register("Linux", "linux系统", "linux操作系统", "unix", "centos", "ubuntu")
_register("Windows Server", "windows server")
_register("PyTorch", "pytorch")
_register("TensorFlow", "tensorflow")
_register("Keras", "keras")
_register("Scikit-learn", "sklearn", "scikit learn")
_register("Pandas", "pandas")
_register("NumPy", "numpy")
_register("OpenCV", "opencv")
_register("机器学习", "machine learning", "ml")
_register("深度学习", "deep learning", "dl")
_register("自然语言处理", "nlp")
_register("计算机视觉", "cv", "图像识别", "图像处理")
_register("强化学习", "reinforcement learning")
_register("大模型", "llm", "大语言模型", "large language model")
_register("Transformer", "transformer")
_register("BERT", "bert")
_register("数据挖掘")
_register("数据分析")
_register("数据标注")
_register("特征工程")
_register("数据可视化")
_register("Selenium", "selenium")
_register("Appium", "appium")
_register("JMeter", "jmeter")
_register("Postman", "postman")
_register("Jira", "jira")
_register("TestNG", "testng")
_register("Pytest", "pytest")
_register("JUnit", "junit")
_register("Robot Framework", "robotframework")
_register("Charles", "charles")
_register("Fiddler", "fiddler")
_register("LoadRunner", "loadrunner")
_register("功能测试")
_register("接口测试")
_register("性能测试")
_register("自动化测试")
_register("测试用例", "测试用例设计")
_register("缺陷跟踪", "缺陷跟踪与管理", "缺陷管理")
_register("兼容性测试")
_register("Android", "安卓")
_register("iOS", "ios开发")
_register("Flutter", "flutter")
_register("React Native", "reactnative")
_register("微信小程序", "小程序开发")
_register("uni-app", "uniapp")
_register("AWS", "亚马逊云")
_register("Azure")
_register("阿里云", "aliyun")
_register("腾讯云")
_register("华为云")
_register("微服务")
_register("分布式")
_register("高并发")
_register("项目管理")
_register("需求分析")
_register("产品设计")
_register("原型设计", "axure", "axure rp")
_register("Visio")
_register("Excel", "excel")
_register("Word", "word")
_register("PowerPoint", "ppt")
_register("Office", "office办公软件", "wps")
_register("沟通能力", "沟通协调能力", "沟通")
_register("协调能力", "协调")
_register("团队合作", "团队合作精神", "团队协作", "团队意识")
_register("学习能力")
_register("抗压能力", "抗压")
_register("责任心")
_register("执行力")
_register("独立思考")
_register("独立研究能力")
_register("独立工作能力")
_register("英文读写", "英语读写", "英文阅读", "英语")
_register("科研能力")

#: 词表（规范名，去重后按**长度降序**用于最长匹配）
TECH_VOCABULARY: tuple[str, ...] = tuple(
    sorted(set(_SKILL_ALIASES.values()), key=lambda term: (-len(term), term))
)

_WS = re.compile(r"\s+")
#: 修饰词之间的连接符（`、`/`,`/`/`/空）
_MODIFIER_SEP = re.compile(r"[\s、,，/·]+")
#: 修饰词按**长度降序**（贪心剥离时长词优先，`熟练掌握` 不会被 `熟练` 抢先）
_MODIFIERS_BY_LENGTH: tuple[str, ...] = tuple(
    sorted(_SKILL_MODIFIERS, key=lambda word: (-len(word), word))
)


def _clean(text: object) -> str:
    if text is None:
        return ""
    return _WS.sub(" ", str(text)).strip()


def _is_ascii_term(term: str) -> bool:
    return all(ord(ch) < 128 for ch in term)


def _find_term(haystack_lower: str, term: str) -> int:
    """在（已转小写的）技能串里定位词表词；找不到返回 -1。

    ⚠️ 拉丁词用**词边界**匹配：否则 `Go` 会命中 `Google`、`Java` 会命中 `JavaScript`。
    CJK 词没有词边界概念，直接用子串查找。
    """
    term_lower = term.lower()
    if _is_ascii_term(term):
        pattern = r"(?<![a-z0-9])" + re.escape(term_lower) + r"(?![a-z0-9])"
        match = re.search(pattern, haystack_lower)
        return match.start() if match else -1
    return haystack_lower.find(term_lower)


def _strip_modifiers(piece: str) -> bool:
    """贪心剥掉首尾的已知修饰词；**全部剥光**返回 True。

    为什么要贪心而不是"整片比对"：真实技能串里的修饰词是**连写**的 ——
    `具备Java开发经验` 的后缀是 `开发经验`（两个修饰词粘在一起），
    整片比对认不出来。贪心剥离能处理任意组合，且每轮都会变短、必然终止。
    """
    changed = True
    while piece and changed:
        changed = False
        for modifier in _MODIFIERS_BY_LENGTH:
            if piece.startswith(modifier):
                piece = piece[len(modifier) :]
                changed = True
                break
            if piece.endswith(modifier):
                piece = piece[: -len(modifier)]
                changed = True
                break
    return not piece


def _modifiers_only(fragment: str) -> bool:
    """片段是否**全部由修饰词组成**（空片段也算）。"""
    text = fragment.strip().strip("的").strip()
    if not text:
        return True
    for piece in _MODIFIER_SEP.split(text):
        if piece and not _strip_modifiers(piece):
            return False
    return True


def normalise_skill(skill: object) -> str:
    """把单个技能串归约成**最基础的技术名词**。

    * 命中别名 → 直接用规范名（`springboot` / `spring-boot` → `Spring Boot`）；
    * 否则按**最长已知词**匹配，且左右剩余部分全是修饰词才归约
      （`Java开发` → `Java`、`MySQL数据库` → `MySQL`）；
    * 都不满足 → **原样保留**（宁可不归约，也不瞎猜）。
    """
    text = _clean(skill)
    if not text:
        return ""

    lowered = text.lower()

    # ① 别名精确命中
    alias = _SKILL_ALIASES.get(lowered)
    if alias:
        return alias

    # ② 最长已知词 + 左右都是修饰词 → 归约
    for term in TECH_VOCABULARY:
        index = _find_term(lowered, term)
        if index < 0:
            continue
        prefix = lowered[:index]
        suffix = lowered[index + len(term) :]
        if _modifiers_only(prefix) and _modifiers_only(suffix):
            return term

    # ③ 原样保留
    return text


def normalise_skills(skills: object, *, limit: int | None = None) -> list[str]:
    """批量归约 + 去重（保序）＋可选数量上限。

    * 同一个规范名只保留第一次出现（大小写不同视为同一个）；
    * `limit` 给定时截断（用户在 B4 定了核心 ≤20 / 加分 ≤10）。
    """
    if not skills:
        return []
    items = skills if isinstance(skills, list | tuple | set) else [skills]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        canonical = normalise_skill(item)
        if not canonical:
            continue
        key = canonical.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(canonical)
        if limit is not None and len(out) >= limit:
            break
    return out


def unmapped_skills(skills: object) -> list[str]:
    """哪些技能**没进词表**（归约后仍是原文且不等于任何规范名）。

    用途：人工按这份清单补词表 —— 词表覆盖率是这套方案唯一的运维成本，
    所以要能一眼看到"还缺哪些"。
    """
    if not skills:
        return []
    items = skills if isinstance(skills, list | tuple | set) else [skills]
    known = {term.lower() for term in TECH_VOCABULARY}
    out: list[str] = []
    for item in items:
        canonical = normalise_skill(item)
        if canonical and canonical.lower() not in known:
            out.append(canonical)
    return out


def match_skill_overlap(
    student_skills: object,
    job_skills: object,
) -> dict:
    """算「学生技能 ∩ 岗位核心技能」的命中情况（B5 的显式技能维度）。

    两侧都先归约成规范名，所以 `Java开发` 与 `Java` 算命中、
    `SpringBoot` 与 `Spring Boot` 也算命中。

    Returns:
        ``{"matched": [...], "missing": [...], "student_only": [...],
           "job_total": n, "student_total": m, "hit_ratio": 0.625}``

        `hit_ratio` = 命中数 / 岗位核心技能数（岗位侧为空时视为 0.0，
        由调用方决定是否把这一维计入总分 —— "岗位没写技能"不等于"学生全命中"）。
    """
    student = normalise_skills(student_skills)
    job = normalise_skills(job_skills)

    student_keys = {s.lower(): s for s in student}
    job_keys = {j.lower(): j for j in job}

    matched = [job_keys[k] for k in job_keys if k in student_keys]
    missing = [job_keys[k] for k in job_keys if k not in student_keys]
    student_only = [student_keys[k] for k in student_keys if k not in job_keys]
    job_total = len(job_keys)

    return {
        "matched": matched,
        "missing": missing,
        "student_only": student_only,
        "job_total": job_total,
        "student_total": len(student_keys),
        "hit_ratio": round(len(matched) / job_total, 3) if job_total else 0.0,
    }
