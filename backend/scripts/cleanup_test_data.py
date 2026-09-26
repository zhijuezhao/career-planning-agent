#!/usr/bin/env python
"""数据卫生清理（P1b）：只删**可确认的测试数据**，真实数据一律保留。

背景：9/15–9/26 期间跑了大量全量测试，库里堆了 2181 个测试用户、882 条测试导入任务、
315 条测试岗位画像……2026-09-26 真实导入（job #852/#853，82 条画像 + 2 条 D 级归档）
落库后，用户要求"真实数据入库后再清"。

设计要点（为什么这么写）：

1. **删除靠"识别测试模式"，不靠"保留白名单"**：白名单式（"除了 X 全删"）在用户以后
   新建真实账号后重跑会把真实数据一起删掉；本脚本按**已核对的测试命名模式**删除，
   不匹配的一律保留。`--keep-user` 只是额外保险。
2. **默认 dry-run**：不加 `--apply` 只报告"将删什么、删多少"，不动一个字节。
3. **先备份到仓库外**：`--apply` 时先把**将被删除的每一行**导出成 CSV（`--backup-dir`，
   默认 `%TEMP%`），并强制校验备份目录不在仓库内；备份失败即中止。
4. **单事务 + 外键顺序**：子表先于父表，任何一步失败整体回滚（不会删一半）。
5. **磁盘文件一起清**：`uploads/import/` 的测试 CSV、被删用户的 `uploads/user_<id>/`、
   被删报告记录对应的 `output/reports/*.docx`。用 `--no-clean-files` 可只清库。
6. **不动清单**：本脚本只碰数据库 + `uploads/`、`output/`，绝不写 `app/`、`docker-compose.yml`、
   alembic、前端。

用法：
    # ① 宿主机（postgres 端口已发布到 5432）
    python backend/scripts/cleanup_test_data.py                 # 报告（dry-run）
    python backend/scripts/cleanup_test_data.py --apply         # 执行

    # ② 容器内（容器 CWD = /app/backend）
    docker exec -w /app/backend career_backend python scripts/cleanup_test_data.py

常用开关：
    --apply                     真正删除（不加只报告）
    --delete-user NAME          追加删除"不匹配测试模式、但经人工确认"的账号（可重复）
    --keep-user NAME            额外保底保留（可重复；`s7admin` 永远保留）
    --backup-dir DIR            被删行 CSV 的落点（必须在仓库外，默认 %TEMP%/sjv-cleanup-<ts>）
    --no-clean-files            只清库，不动 uploads/ 与 output/reports/ 的磁盘文件

数据库地址优先级：--database-url > 环境变量 DATABASE_URL > backend/.env（get_settings()）> 内置默认值。
Windows 控制台若中文乱码，先执行: chcp 65001
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_planning"

# --------------------------------------------------------------------------------------
# 一、识别规则（每一条都对应 2026-09-26 实测核对过的命名模式）
# --------------------------------------------------------------------------------------

# 测试用户：全部来自 `tests/` 与验收脚本自建账号。**刻意不写 `^admin`/`^student` 通配**，
# 否则会误删手工建的 `admin`（id=486）；`zhijuezhao`（id=485）同样不匹配任何模式 → 保留。
TEST_USER_PATTERNS = (
    r"^admin_(test_)?[a-z_]*[0-9]{6,}",  # admin_1789565669 / admin_career_... / admin_test_*
    r"^student_(test_)?[a-z_]*[0-9]{6,}",
    r"^test",  # test* / test_admin_* / test13_*
    r"^journey_[0-9]",
    r"^t13_user_",
    r"^t12_2_user_",
    r"^reg_?[0-9]",
    r"^dup_[0-9]",
    r"^login_[0-9]",
    r"^wrongpw_[0-9]",
    r"^meuser_[0-9]",
    r"^resume_user_[0-9]",
    r"^match_[0-9]",
    r"^rec_[0-9]",
    r"^snap_[0-9]",
    r"^other_",
    r"^bypass_",
    r"^probe",
    r"^compat",
    r"^verify_",
    r"^accept_?[0-9a-z]*$",  # accept11 / accept_biz / accept_new
    r"^chattest",
    r"^perf_",
    r"^load_",
    r"^e2e_",
)

# 保底保留（即使将来模式误伤也不删）：管理端登录账号。
KEEP_USERS = frozenset({"s7admin"})

# 测试岗位画像标题：`tests/test_api/test_admin_jobs.py` 固定产出的 5 种前缀。
# 交叉核对（2026-09-26）：不匹配这 5 种模式的 82 行**恰好**落在 #852(3 行) 与 #853(79 行)
# 两个批次时间戳上 → 分类无歧义。
TEST_JOB_TITLE_PATTERNS = (
    r"^测试岗位_",
    r"^测试岗位详情_",
    r"^更新后岗位_",
    r"^互联网岗位_",
    r"^金融岗位$",
)

# 测试导入任务文件名：S7/S7-1/S7-3 测试套件上传物 + 路径穿越负例。
# 库里存的是原始文件名（`s73_stage.csv`），磁盘上带 `<job_id>_` 前缀（`183_s73_stage.csv`）
# → 两边都先用 `_strip_job_prefix()` 归一化再匹配。
TEST_IMPORT_FILE_PATTERNS = (
    r"^s7",  # s71_* / s73_* / s7_live3.csv
    r"test\.csv$",  # test.csv / process_test.csv
    r"evil\.csv$",  # ../../evil.csv（路径穿越负例）
    r"\.\./",
)

_JOB_PREFIX = re.compile(r"^\d+_")


def _strip_job_prefix(name: str) -> str:
    """去掉磁盘文件名上的 `<job_id>_` 前缀（`183_s73_stage.csv` → `s73_stage.csv`）。"""
    return _JOB_PREFIX.sub("", name, count=1)


def _is_test_import_name(name: str) -> bool:
    base = _strip_job_prefix(name)
    return any(re.search(p, base) for p in TEST_IMPORT_FILE_PATTERNS)


def _test_import_sql(column: str) -> str:
    """库侧等价条件：`file_name` 去不掉前缀（本来就没有），直接锚定测试名。"""
    return (
        f"({column} ~ '^s7' OR {column} ~ 'test\\.csv$'"
        f" OR {column} ~ 'evil\\.csv$' OR {column} LIKE '%../%')"
    )


def _like_any(column: str, patterns: tuple[str, ...]) -> str:
    """生成 `col ~ 'p1' OR col ~ 'p2' ...` 的 PostgreSQL 正则条件。"""
    return " OR ".join(f"{column} ~ '{p}'" for p in patterns)


TEST_USER_WHERE = _like_any("username", TEST_USER_PATTERNS)
TEST_JOB_WHERE = _like_any("title", TEST_JOB_TITLE_PATTERNS)
TEST_IMPORT_WHERE = _test_import_sql("file_name")

# 测试维度权重：`test_admin_matching.py` 用固定中文前缀 + 时间戳建权重行。
# 2026-09-26 实测：288 行**全部**是这 4 个前缀，无一行是真实配置
# （真实配置应由管理员在「匹配 → 维度权重」里建，`job_category` 会是真实岗位类别名）。
TEST_WEIGHT_PATTERNS = (
    r"^测试类别_[0-9]+$",
    r"^重复类别_[0-9]+$",
    r"^更新类别_[0-9]+$",
    r"^筛选类别_[0-9]+$",
)
TEST_WEIGHT_WHERE = _like_any("job_category", TEST_WEIGHT_PATTERNS)


@dataclass(frozen=True)
class Rule:
    """一条删除规则：表 + 条件 + 为什么要删（打印给人看）。"""

    table: str
    where: str
    reason: str
    key: str = "id"  # 收集被删主键/外键时用哪一列


# **顺序即外键顺序**：子表在前，父表在后（chat_messages→chat_sessions→…→users）。
#
# `where` 里的 `{users}` / `{jobs}` 占位符在运行时替换成"将要被删的用户/岗位"子查询
# （见 `_user_subquery()` / `_job_subquery()`）。**刻意不用 `TRUE`**：本脚本会被反复
# 使用（每跑一次全量测试就要用一次），一句 `DELETE FROM chat_sessions` 在用户以后
# 有了真实会话时会连真实数据一起删掉；按"归属"删才安全。
RULES: tuple[Rule, ...] = (
    Rule(
        "chat_messages",
        "session_id IN (SELECT id FROM chat_sessions WHERE user_id IN ({users}))",
        "只删测试账号名下会话里的消息",
    ),
    Rule("chat_sessions", "user_id IN ({users})", "只删测试账号的会话"),
    Rule("report_records", "user_id IN ({users})", "只删测试账号的报告记录"),
    Rule("profile_snapshots", "user_id IN ({users})", "只删测试账号的画像快照"),
    Rule("student_profiles", "user_id IN ({users})", "只删测试账号的学生档案"),
    Rule(
        "dimension_scores",
        "profile_type = 'job' AND profile_id IN ({jobs})",
        "只删指向被测岗位的维度分（profile_type 是多态列，无外键）",
    ),
    Rule(
        "dimension_weights",
        TEST_WEIGHT_WHERE,
        "只删测试建的权重行（测试类别/重复类别/更新类别/筛选类别 + 时间戳）",
    ),
    Rule("job_match_embeddings", "job_profile_id IN ({jobs})", "只删被测岗位的向量"),
    Rule(
        "job_match_records",
        "job_profile_id IN ({jobs})"
        " OR profile_snapshot_id IN (SELECT id FROM profile_snapshots WHERE user_id IN ({users}))",
        "只删被测岗位 / 测试快照的匹配明细",
    ),
    Rule("resumes", "user_id IN ({users})", "只删测试账号的简历记录"),
    Rule(
        "users",
        TEST_USER_WHERE,
        "测试自建账号（s7admin 由 KEEP_USERS 保底；--delete-user 追加人工确认账号）",
    ),
    Rule("job_profiles", TEST_JOB_WHERE, "5 种测试标题前缀；真实 82 行（#852/#853）不在其中"),
    Rule(
        "data_import_jobs",
        TEST_IMPORT_WHERE,
        "S7/S7-1/S7-3 测试上传；真实上传(238/239/336/852/853)不在其中",
    ),
)

# 这些表**一行都不删**（真实配置 / 真实数据），写在这里是为了让报告显式说明"为什么没动"。
KEEP_TABLES: tuple[tuple[str, str], ...] = (
    ("job_raw_data", "87 行全部来自真实导入（#852 3 行 + #853 82 行 + D 级归档 2 行）"),
    ("llm_providers / llm_models / llm_routes", "真实模型配置（含 default 绑定）"),
    ("companies / job_company_links", "当前 0 行"),
    ("career_knowledge", "当前 0 行"),
)


# --------------------------------------------------------------------------------------
# 二、备份（仓库外 CSV）
# --------------------------------------------------------------------------------------


@dataclass
class TableResult:
    table: str
    total_before: int = 0
    matched: int = 0
    deleted: int = 0
    total_after: int = 0
    backup_path: str = ""
    keys: list = field(default_factory=list)


def _assert_backup_outside_repo(backup_dir: Path) -> None:
    try:
        backup_dir.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return
    raise RuntimeError(f"备份目录必须在仓库外，拒绝写入 {backup_dir}（仓库根 {REPO_ROOT}）")


async def _count(conn: AsyncConnection, table: str, where: str) -> int:
    return int((await conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"))).scalar() or 0)


async def _rows(conn: AsyncConnection, table: str, where: str):
    result = await conn.execute(text(f"SELECT * FROM {table} WHERE {where}"))
    columns = list(result.keys())
    return columns, result.fetchall()


def _write_csv(path: Path, columns: list[str], rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


async def _backup_table(conn: AsyncConnection, rule: Rule, backup_dir: Path) -> tuple[str, list]:
    columns, rows = await _rows(conn, rule.table, rule.where)
    path = backup_dir / f"{rule.table}.csv"
    _write_csv(path, columns, rows)
    key_index = columns.index(rule.key) if rule.key in columns else 0
    return str(path), [row[key_index] for row in rows]


# --------------------------------------------------------------------------------------
# 三、磁盘文件清理
# --------------------------------------------------------------------------------------


def _test_import_file(name: str) -> bool:
    return _is_test_import_name(name)


@dataclass
class FileResult:
    kind: str
    removed: int = 0
    kept: int = 0
    samples: list[str] = field(default_factory=list)


def clean_files(
    *,
    deleted_user_ids: list,
    deleted_report_paths: list[str],
    uploads_dir: Path,
    reports_dir: Path,
    apply: bool,
) -> list[FileResult]:
    """删除测试上传物 / 被删用户的简历目录 / 被删报告的 docx。"""
    results: list[FileResult] = []

    # ① uploads/import/ 测试 CSV（真实上传的 xlsx 不在模式内）
    res = FileResult("uploads/import（测试 CSV）")
    import_dir = uploads_dir / "import"
    if import_dir.is_dir():
        for path in sorted(import_dir.iterdir()):
            if not path.is_file():
                continue
            if _test_import_file(path.name):
                res.removed += 1
                if len(res.samples) < 3:
                    res.samples.append(path.name)
                if apply:
                    path.unlink(missing_ok=True)
            else:
                res.kept += 1
    results.append(res)

    # ② uploads/user_<id>/（被删用户的简历目录）
    res = FileResult("uploads/user_<id>（被删用户简历）")
    deleted_ids = {str(i) for i in deleted_user_ids}
    for path in sorted(uploads_dir.glob("user_*")):
        if not path.is_dir() or path.name.removeprefix("user_") not in deleted_ids:
            continue
        files = [p for p in path.rglob("*") if p.is_file()]
        res.removed += len(files)
        if len(res.samples) < 3:
            res.samples.append(path.name)
        if apply:
            for file in files:
                file.unlink(missing_ok=True)
            for sub in sorted(path.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            path.rmdir()
    results.append(res)

    # ③ output/reports/*.docx（被删报告记录的实际文件）
    res = FileResult("output/reports（被删报告的 docx）")
    wanted = {Path(p).name for p in deleted_report_paths if p}
    if reports_dir.is_dir():
        for path in sorted(reports_dir.iterdir()):
            if path.is_file() and path.name in wanted:
                res.removed += 1
                if len(res.samples) < 3:
                    res.samples.append(path.name)
                if apply:
                    path.unlink(missing_ok=True)
    results.append(res)
    return results


# --------------------------------------------------------------------------------------
# 四、主流程
# --------------------------------------------------------------------------------------


async def cleanup(database_url: str, *, apply: bool, backup_dir: Path, keep_users: set[str],
                  extra_users: set[str], clean_disk: bool, uploads_dir: Path,
                  reports_dir: Path) -> int:
    engine = create_async_engine(database_url, poolclass=NullPool)
    results: list[TableResult] = []
    deleted_user_ids: list = []
    deleted_report_paths: list[str] = []
    try:
        async with engine.begin() as conn:
            # 0) 保底保留账号必须存在（防止 keep 名单写错后把管理端账号删掉）
            for name in keep_users:
                exists = await conn.execute(
                    text("SELECT count(*) FROM users WHERE username = :n"), {"n": name}
                )
                if not int(exists.scalar() or 0):
                    raise RuntimeError(f"保底保留账号 {name!r} 在库里不存在，拒绝执行（请核对 --keep-user）")

            # 1) 逐表统计 + 备份 + 删除
            #
            # 先算出"这次要删哪些用户 / 哪些岗位"的子查询，再把它填进各表的 `{users}` /
            # `{jobs}` 占位符 —— 子表按**归属**删，真实用户/真实岗位名下的行永远不会被牵连。
            users_where = TEST_USER_WHERE
            if extra_users:
                names = ", ".join(f"'{u}'" for u in sorted(extra_users))
                users_where = f"({users_where} OR username IN ({names}))"
            if keep_users:
                keep = ", ".join(f"'{u}'" for u in sorted(keep_users))
                users_where = f"({users_where}) AND username NOT IN ({keep})"
            subqueries = {
                "users": f"SELECT id FROM users WHERE {users_where}",
                "jobs": f"SELECT id FROM job_profiles WHERE ({TEST_JOB_WHERE})",
            }

            for rule in RULES:
                # 只对**带占位符**的规则做替换：`TEST_USER_WHERE` 里的正则含 `{6,}`，
                # 无条件 `.format()` 会把它当成格式字段而 KeyError（实测踩过）。
                if "{users}" in rule.where or "{jobs}" in rule.where:
                    where = rule.where.format(**subqueries)
                else:
                    where = rule.where
                if rule.table == "users":
                    where = users_where
                total_before = int(
                    (await conn.execute(text(f"SELECT count(*) FROM {rule.table}"))).scalar() or 0
                )
                matched = await _count(conn, rule.table, where)
                item = TableResult(rule.table, total_before=total_before, matched=matched)

                if matched:
                    path, keys = await _backup_table(conn, Rule(rule.table, where, rule.reason, rule.key), backup_dir)
                    item.backup_path, item.keys = path, keys
                    if rule.table == "users":
                        deleted_user_ids = keys
                    if rule.table == "report_records":
                        columns, rows = await _rows(conn, rule.table, where)
                        idx = columns.index("word_file_path")
                        deleted_report_paths = [r[idx] for r in rows if r[idx]]
                    if apply:
                        await conn.execute(text(f"DELETE FROM {rule.table} WHERE {where}"))

                item.deleted = matched if apply else 0
                item.total_after = total_before - item.deleted
                results.append(item)

            # 2) 事务内自检：真实数据必须一行不少（用**反向条件**数，dry-run/apply 都成立）
            keep_list = ", ".join(f"'{u}'" for u in sorted(keep_users))
            verify = {
                "真实岗位画像（期望 82）": (
                    f"SELECT count(*) FROM job_profiles WHERE NOT ({TEST_JOB_WHERE})"
                ),
                "真实导入任务（期望 5）": (
                    f"SELECT count(*) FROM data_import_jobs WHERE NOT ({TEST_IMPORT_WHERE})"
                ),
                "job_raw_data（期望 87）": "SELECT count(*) FROM job_raw_data",
                f"保留账号（期望 {len(keep_users)}）": (
                    f"SELECT count(*) FROM users WHERE username IN ({keep_list})"
                ),
            }
            checks = {
                label: int((await conn.execute(text(sql))).scalar() or 0)
                for label, sql in verify.items()
            }

            if not apply:
                await conn.rollback()  # dry-run：即便上面没写也会回滚，双保险

        # 3) 磁盘清理在事务提交后做（库删成功才删文件）
        file_results: list[FileResult] = []
        if clean_disk:
            file_results = clean_files(
                deleted_user_ids=deleted_user_ids,
                deleted_report_paths=deleted_report_paths,
                uploads_dir=uploads_dir,
                reports_dir=reports_dir,
                apply=apply,
            )
    finally:
        await engine.dispose()

    _print_report(results, checks, file_results, apply=apply, backup_dir=backup_dir)
    return 0


def _print_report(results, checks, file_results, *, apply: bool, backup_dir: Path) -> None:
    mode = "APPLY（已删除）" if apply else "DRY-RUN（未删除任何行）"
    print(f"\n===== 数据卫生清理报告 [{mode}] =====", flush=True)
    print(f"{'表':<24}{'清理前':>9}{'命中':>8}{'已删':>8}{'清理后':>9}", flush=True)
    print("-" * 62, flush=True)
    for r in results:
        print(f"{r.table:<24}{r.total_before:>9}{r.matched:>8}{r.deleted:>8}{r.total_after:>9}", flush=True)
    print("-" * 62, flush=True)
    print(f"命中合计 = {sum(r.matched for r in results)} 行", flush=True)

    if file_results:
        print("\n----- 磁盘文件 -----", flush=True)
        for f in file_results:
            sample = ("，例:" + "、".join(f.samples)) if f.samples else ""
            print(f"{f.kind:<34}{'删除' if apply else '待删'}: {f.removed:<6} 保留: {f.kept}{sample}", flush=True)

    print("\n----- 保留未动 -----", flush=True)
    for name, why in KEEP_TABLES:
        print(f"  {name}: {why}", flush=True)

    print("\n----- 事务内自检 -----", flush=True)
    for label, value in checks.items():
        print(f"  {label} = {value}", flush=True)

    if apply:
        print(f"\n[OK] 备份（被删行的完整 CSV）已写入: {backup_dir}", flush=True)
    else:
        print("\n[提示] 这是 dry-run。确认无误后加 --apply 执行（会先备份到仓库外）。", flush=True)


# --------------------------------------------------------------------------------------
# 五、CLI
# --------------------------------------------------------------------------------------


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def resolve_database_url(cli_value: str | None) -> tuple[str, str]:
    if cli_value:
        return cli_value, "--database-url"
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"], "环境变量 DATABASE_URL"
    try:
        from app.config import get_settings

        return get_settings().database_url, ".env / get_settings()"
    except Exception as exc:  # noqa: BLE001 - .env 不可用不应导致脚本崩溃
        print(
            f"[WARN] 读取 .env 失败（{type(exc).__name__}），回退到内置默认连接串；"
            "如需指定请用 --database-url",
            file=sys.stderr,
        )
        return DEFAULT_DATABASE_URL, "内置默认值（回退）"


def _mask(database_url: str) -> str:
    if "@" in database_url:
        return "..." + database_url[database_url.index("@"):]
    return database_url


def _default_backup_dir() -> Path:
    import tempfile

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / f"sjv-cleanup-{stamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据卫生清理：删除可确认的测试数据（默认 dry-run）")
    parser.add_argument("--database-url", default=None, help="默认取 DATABASE_URL 或 backend/.env")
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只报告）")
    parser.add_argument("--backup-dir", default=None, help="被删行的 CSV 备份目录（必须在仓库外）")
    parser.add_argument("--keep-user", action="append", default=[], help="额外保留的用户名，可重复")
    parser.add_argument(
        "--delete-user",
        action="append",
        default=[],
        help="额外删除的用户名（不匹配任何测试模式、经人工确认的账号），可重复",
    )
    parser.add_argument("--no-clean-files", action="store_true", help="只清库，不动 uploads/output 磁盘文件")
    parser.add_argument("--uploads-dir", default=None, help="默认取 backend/uploads（settings.upload_dir）")
    parser.add_argument("--reports-dir", default=None, help="默认取 backend/output/reports")
    args = parser.parse_args(argv)

    # 切到 backend/ 再读 .env：仓库根 .env 是生产模板（含 Settings 未声明的键）会直接崩。
    os.chdir(BACKEND_DIR)

    uploads_dir = Path(args.uploads_dir) if args.uploads_dir else BACKEND_DIR / "uploads"
    reports_dir = Path(args.reports_dir) if args.reports_dir else BACKEND_DIR / "output" / "reports"
    backup_dir = Path(args.backup_dir) if args.backup_dir else _default_backup_dir()

    url, source = resolve_database_url(args.database_url)
    url = normalize_database_url(url)
    print(f"[INFO] 目标数据库 {_mask(url)}  (来源: {source})", flush=True)
    print(f"[INFO] apply={args.apply}  backup_dir={backup_dir}", flush=True)
    print(f"[INFO] uploads_dir={uploads_dir}", flush=True)

    if args.apply:
        try:
            _assert_backup_outside_repo(backup_dir)
        except RuntimeError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2

    keep_users = set(KEEP_USERS) | set(args.keep_user)
    extra_users = set(args.delete_user) - keep_users
    print(f"[INFO] keep_users={sorted(keep_users)}  extra_delete_users={sorted(extra_users)}", flush=True)
    try:
        return asyncio.run(
            cleanup(
                url,
                apply=args.apply,
                backup_dir=backup_dir,
                keep_users=keep_users,
                extra_users=extra_users,
                clean_disk=not args.no_clean_files,
                uploads_dir=uploads_dir,
                reports_dir=reports_dir,
            )
        )
    except Exception as exc:  # noqa: BLE001 - CLI 入口
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
