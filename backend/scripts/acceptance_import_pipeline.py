#!/usr/bin/env python
"""导入流水线端到端验收（B1–B5）：打**真实 HTTP + 真实 DB**。

为什么要单独一个脚本
--------------------
`pytest` 那 300+ 条用例全在**无 DB 环境**下跑（本机 Postgres 起不来时它们会 error），
而这次改造最关键的几个不变量只有真库才能验：

* 切片清单能落盘、能**从磁盘重算**校验；
* `awaiting_confirmation` 真的停在库里、并能被"继续下一片"放行；
* `(岗位名, 等级)` 唯一键下**同名不同等级是两条画像**；
* `job_raw_data.payload` 真的写进去了（**聚合阶段唯一的数据来源**）；
* `salary_stats` / `aggregate_card` 真的落库（可审计）。

验收项（每项独立 PASS/FAIL）
---------------------------
B1 列映射与清洗   : 城市是纯城市名（不含 `-`）、薪资是月薪量级（不是被 ÷12 的错值）
B2 去重           : 去重没有走 `(岗位名, 公司)` 把编码各异的行并掉（读去重阶段自报的统计）；
                    且上传的每一行都真的落库了（质检是 LLM 判的，**单独一条证据**）
B3 切片与闸门     : manifest 三层校验 0 问题；每片跑完停在 `awaiting_confirmation`；
                    `/process` 可放行下一片；进度只增不减；最后一片 `completed`
B4 分级与聚合     : 同名不同等级 = 多条 profile；`payload`/`salary_stats`/`aggregate_card`
                    落库；六维齐全
B5 技能           : `hard_skills.tags` 已归一化（不出现 `Java开发` 这类带修饰的写法）
幂等              : 再跑一次聚合，profile 数量不变

用法
----
    # 小样本（默认 12 行，约 2 分钟、约 30 次 LLM）：
    docker exec -e PYTHONPATH=/app/backend -e PYTHONIOENCODING=utf-8 -w /app/backend \
        career_backend python scripts/acceptance_import_pipeline.py

    # 真实 524 行全量（约 25 分钟 + 聚合收尾、约 660 次 LLM 调用）：
    ... python scripts/acceptance_import_pipeline.py --full

    # 保留现场排查：
    ... python scripts/acceptance_import_pipeline.py --keep

⚠️ 两个会让人白跑一次的坑：

1. **`--base` 默认 `http://127.0.0.1:8001`** —— 这是**容器内** uvicorn 的端口
   （`docker-compose.yml` 把它映射到宿主 `8002`；`8000` 是 `app_port` 默认值，
   容器里没有任何东西监听它）。在**宿主机**上跑请显式 `--base http://127.0.0.1:8002`。
2. **B3 的暂停闸门要求"至少两片"** —— 片大小由**服务端** `IMPORT_SLICE_SIZE` 决定，
   与 `--rows` 无关。默认 50 时 12 行只会切成 **1 片**，"每片跑完停在
   `awaiting_confirmation`"这条就自动退化成"最后一片 completed"、闸门等于没验。
   要真正验闸门，**用小片大小启动后端**，例如：
       docker exec -d career_backend sh -c "cd /app/backend && IMPORT_SLICE_SIZE=4 \
           PYTHONPATH=/app/backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8010"
       ... python scripts/acceptance_import_pipeline.py --base http://127.0.0.1:8010

退出码：0 = 全通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.core.job_agent.levels import ABS_JUNIOR_MAX  # noqa: E402
from app.core.job_agent.slices import SLICE_SUBDIR, verify_manifest  # noqa: E402
from app.core.skills import CORE_SKILL_LIMIT  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402

PREFIX = f"accimp_{int(time.time())}"
PASSWORD = "AccImp-2026!pass"

#: 真实数据文件（524 行，12 列）—— `--full` 时用它；容器里通常挂在 /data 下
REAL_FILE_CANDIDATES = (
    "/data/原始比赛数据_清洗后.xlsx",
    "/app/backend/uploads/import/原始比赛数据_清洗后.xlsx",
)

#: 小样本用两个岗位名；每个名下凑够 ≥3 条同等级，才能形成一级画像
TITLE_A = f"验收岗位甲（导入验收 {PREFIX}）"
TITLE_B = f"验收岗位乙（导入验收 {PREFIX}）"
ALL_TITLES = (TITLE_A, TITLE_B)

UPLOAD_DIR = Path("uploads/import")

#: 岗位详情（复刻真实表形态：职责 + 任职要求，行内用 `<br>` 换行）。
#:
#: ⚠️ 必须写得像一条**真实招聘**。质检是 LLM 判的：信息太薄就判 D 被丢掉 ——
#: 实测只写一行"负责系统开发"时 12 行里 9 行被判 D（45/46 分），
#: 每个 `(岗位名, 等级)` 组凑不满 `MIN_GROUP_SIZE=3`，阶段 8 的
#: "分组 → 综合卡 → 六维"整条链路就**根本没被验到**（只有 1 个组、1 张卡）。
DETAIL = (
    "岗位职责：<br>"
    "1、负责公司核心业务系统的需求分析、方案设计与编码实现，参与技术评审；<br>"
    "2、负责系统性能优化、线上问题排查与稳定性建设，保障服务高可用；<br>"
    "3、参与代码评审与技术文档编写，沉淀可复用的公共组件。<br>"
    "任职要求：<br>"
    "1、本科及以上学历，计算机相关专业，3 年以上后端开发经验；<br>"
    "2、精通 Java，熟悉 Spring Boot、MySQL、Redis，了解常用设计模式与微服务架构；<br>"
    "3、具备良好的沟通能力、责任心与团队协作精神。"
)

COMPANY_DETAIL = (
    "一家专注于企业级软件与数字化服务的公司，业务覆盖全国 20 多个城市，"
    "团队规模 500 人以上，已服务超过 1000 家企业客户。"
)


class Checker:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: object, detail: str = "") -> bool:
        passed = bool(ok)
        self.results.append((name, passed, detail))
        line = f"[{'PASS' if passed else 'FAIL'}] {name}"
        if detail:
            line += f" | {detail}"
        print(line, flush=True)
        return passed

    def note(self, message: str) -> None:
        print(f"[NOTE] {message}", flush=True)

    def summary(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(
            f"\n[SUMMARY] {len(self.results) - len(failed)}/{len(self.results)} 项通过",
            flush=True,
        )
        if failed:
            print("[FAILED] " + "、".join(failed), file=sys.stderr)
            return 1
        return 0


# ── HTTP ──────────────────────────────────────────────────────────────────────


def http(
    base: str,
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 60,
) -> tuple[int, object]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=body, method=method)  # noqa: S310
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def upload_file(base: str, token: str, filename: str, content: bytes) -> tuple[int, object]:
    boundary = "----accimp" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(base + "/api/v1/admin/import/upload", data=body, method="POST")  # noqa: S310
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


# ── 测试数据：刻意复刻三次真实事故的形态 ──────────────────────────────────────


def build_csv(rows: int) -> bytes:
    """构造小样本 CSV，每一列都在复刻一次真实事故：

    * `地址` 写成 `北京-None` → B1 的 `-None` 脏值（原实现在 17/524 行上）
    * `薪资范围` 混入 `1.2-1.3万` → B1 的"万被当年薪 ÷12"（原错 12 倍）
    * `岗位详情` 带 `<br>` → B1 的 HTML 未清洗（原 `html_tags_removed=0`）
    * 同名同公司但 `岗位编码` 不同 → B2 的"整表被名称合并塌成 1 条"
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["岗位名称", "地址", "薪资范围", "公司名称", "所属行业", "公司规模",
         "公司类型", "岗位编码", "岗位详情", "更新日期", "公司详情", "岗位来源地址"]
    )
    half = max(rows // 2, 1)
    for index in range(rows):
        title = TITLE_A if index < half else TITLE_B
        # 前 3 条走"低薪档"，其余走高薪档 → 每个岗位名下能形成两个等级组
        low_tier = index % max(half, 1) < 3
        salary = "5000-6000元" if low_tier else "1.2-1.3万"
        writer.writerow([
            title,
            "北京-None" if index % 3 == 0 else "上海-杨浦区",
            salary,
            f"{PREFIX} 公司{index % 3}",
            "计算机软件",
            "100-499人",
            "民营",
            f"{PREFIX}CODE{index:04d}",  # 编码各不相同 → 一行都不该被合并掉
            DETAIL,
            "2026/07/04",
            COMPANY_DETAIL,
            f"https://example.com/jobdetail/{PREFIX}{index:04d}.htm?preactionid=abc",
        ])
    return buffer.getvalue().encode("utf-8-sig")


def find_real_file() -> Path | None:
    for candidate in REAL_FILE_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return None


# ── DB 侧 ─────────────────────────────────────────────────────────────────────


async def setup_admin(username: str) -> None:
    from sqlalchemy import text

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE username = :u"), {"u": username}
        )
        await session.commit()


async def count_sql(sql: str, params: dict | None = None) -> int:
    from sqlalchemy import text

    async with async_session_factory() as session:
        return int((await session.execute(text(sql), params or {})).scalar_one())


async def fetch_rows(sql: str, params: dict | None = None) -> list[tuple]:
    from sqlalchemy import text

    async with async_session_factory() as session:
        return list((await session.execute(text(sql), params or {})).all())


async def wait_for_aggregation(
    base: str, token: str, job_id: int, timeout: int
) -> tuple[int, object]:
    """等阶段 8 把 `stats.aggregate` 写进工单（或超时）。

    ⚠️ `status == "completed"` **不代表聚合已完成**。`_import_runner._run_pipeline`
    先把最后一片落成 `completed`（原始数据确实完整入库了），**然后**才跑阶段 8 ——
    这是有意的（聚合失败不该让已入库的数据看起来"没导进来"）。所以这里必须盯
    `stats.aggregate` 这个**收尾信号**，而不是 `status`：实测 12 行样本的聚合要 40 余秒，
    真实 87 组要几分钟；一到 completed 就读 stats 必然读到"还没写"，
    会把"聚合正在跑"误判成"聚合没跑"。
    """
    deadline = time.monotonic() + timeout
    code, detail = 0, {}
    while time.monotonic() < deadline:
        code, detail = http(base, f"/api/v1/admin/import/{job_id}", token=token)
        if code == 200 and ((detail.get("stats") or {}).get("aggregate")):
            return code, detail
        await asyncio.sleep(3)
    print(f"[NOTE] 等阶段 8 聚合超过 {timeout}s 仍未看到 stats.aggregate", flush=True)
    return code, detail


async def cleanup(username: str, keep: bool, job_ids: list[int], *, full: bool = False) -> None:
    from sqlalchemy import text

    if keep:
        print(f"[cleanup] --keep：保留现场（前缀 {PREFIX}）", flush=True)
        return

    if full:
        # `--full` 导的是**真实表**：那批原始行与岗位画像就是本次要的产物
        # （第一波岗位画像构建），删掉等于把刚验完的东西扔掉 → 只回收临时管理员。
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM users WHERE username = :u"), {"u": username})
            await session.commit()
        print("[cleanup] --full：真实数据与工单保留（只回收临时管理员）", flush=True)
        return

    async with async_session_factory() as session:
        for title in ALL_TITLES:
            await session.execute(
                text(
                    "DELETE FROM job_match_embeddings WHERE job_profile_id IN "
                    "(SELECT id FROM job_profiles WHERE title = :t)"
                ),
                {"t": title},
            )
        # 本次导入写进去的岗位/原始行：按前缀标题 + 编码前缀双重兜底
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"%{PREFIX}%"})
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p OR title = ANY(:t)"),
            {"p": f"%{PREFIX}%", "t": list(ALL_TITLES)},
        )
        await session.execute(
            text("DELETE FROM data_import_jobs WHERE file_name LIKE :p"), {"p": f"{PREFIX}%"}
        )
        # 只删"删完岗位后没人关联"的公司
        await session.execute(
            text(
                "DELETE FROM companies WHERE name LIKE :p AND NOT EXISTS "
                "(SELECT 1 FROM job_company_links WHERE company_id = companies.id)"
            ),
            {"p": f"{PREFIX}%"},
        )
        await session.execute(text("DELETE FROM users WHERE username = :u"), {"u": username})
        await session.commit()

    for job_id in job_ids:
        for path in UPLOAD_DIR.glob(f"{job_id}_*"):
            path.unlink(missing_ok=True)
        slice_dir = UPLOAD_DIR / SLICE_SUBDIR / f"job{job_id}"
        if slice_dir.exists():
            for path in slice_dir.iterdir():
                path.unlink(missing_ok=True)
            slice_dir.rmdir()
    print(f"[cleanup] 已清理 {len(job_ids)} 个工单的落盘文件", flush=True)


# ── 主流程 ────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace, checker: Checker) -> int:
    import shutil

    base = args.base.rstrip("/")
    settings = get_settings()
    username = f"{PREFIX}_admin"

    # 1) 临时管理员
    status, payload = http(
        base,
        "/api/v1/auth/register",
        method="POST",
        payload={"username": username, "password": PASSWORD, "email": f"{username}@x.com"},
    )
    if status not in (200, 201):
        print(f"[FATAL] 注册临时管理员失败：{status} {payload}", file=sys.stderr)
        return 1
    await setup_admin(username)
    status, payload = http(
        base,
        "/api/v1/admin/auth/login",
        method="POST",
        payload={"username": username, "password": PASSWORD},
    )
    if status != 200:
        print(f"[FATAL] 登录失败：{status} {payload}", file=sys.stderr)
        return 1
    token = payload["access_token"]

    checker.check(
        "聚合开关已打开（否则阶段 8 不跑）",
        settings.import_aggregate_enabled,
        f"IMPORT_AGGREGATE_ENABLED={settings.import_aggregate_enabled}",
    )

    # 1.5) 记下**导入前**的原始行水位。
    #      `job_raw_data` 不回写 job_id，所以"本次导入了哪些行"只能用 id 圈定；
    #      `--full` 用的是真实岗位名（"APP推广"…，不带验收前缀），按标题过滤根本圈不到。
    raw_marker = await count_sql("SELECT coalesce(max(id), 0) FROM job_raw_data")

    # 2) 上传（小样本 or 真实 524 行）
    job_ids: list[int] = []
    if args.full:
        real = find_real_file()
        if real is None:
            checker.note(f"--full 找不到真实文件，已试：{REAL_FILE_CANDIDATES}")
            checker.note("改为跑小样本")
            args.full = False
    if args.full:
        content = real.read_bytes()  # type: ignore[union-attr]
        filename = f"{PREFIX}_{real.name}"  # type: ignore[union-attr]
    else:
        content = build_csv(args.rows)
        filename = f"{PREFIX}_acceptance.csv"

    status, payload = upload_file(base, token, filename, content)
    if status != 201:
        print(f"[FATAL] 上传失败：{status} {payload}", file=sys.stderr)
        return 1
    job_id = int(payload["id"])
    job_ids.append(job_id)
    stats = payload.get("stats") or {}
    slices = stats.get("slices") or {}
    total_rows = int(slices.get("total_rows") or 0)
    slice_count = int(slices.get("slice_count") or 0)
    slice_size = int(slices.get("slice_size") or 0)
    checker.check("上传即切片", slice_count >= 1, f"总行 {total_rows} / 片大小 {slice_size} / 片数 {slice_count}")

    # 3) 三层完整性校验（**从磁盘重算**）
    slice_dir = UPLOAD_DIR / SLICE_SUBDIR / f"job{job_id}"
    manifest_path = slice_dir / str(slices.get("manifest_file") or "")
    checker.check("manifest 已落盘", manifest_path.exists(), str(manifest_path))
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing = [s["file"] for s in manifest["slices"] if not (slice_dir / s["file"]).exists()]
        checker.check("每片文件都在", not missing, f"缺失 {missing}" if missing else "")
        problems = verify_manifest(manifest, slice_dir)
        checker.check("三层完整性校验 0 问题", not problems, "; ".join(problems))
        checker.check(
            "行数之和 == 原表行数",
            manifest["integrity"]["rows_sum"] == manifest["total_rows"],
            f"{manifest['integrity']['rows_sum']} == {manifest['total_rows']}",
        )
    else:
        checker.check("三层完整性校验 0 问题", False, "manifest 不存在")

    # 4) 逐片推进，每片必须停在 awaiting_confirmation（除最后一片）
    seen_processed: list[int] = []
    for expected in range(1, slice_count + 1):
        status, payload = http(base, f"/api/v1/admin/import/{job_id}/process", token=token, method="POST")
        checker.check(f"第 {expected} 片可启动 /process", status == 200, f"{status}")

        # 后台任务是异步的：轮询到本轮结束
        deadline = time.monotonic() + args.slice_timeout
        last = {}
        while time.monotonic() < deadline:
            code, last = http(base, f"/api/v1/admin/import/{job_id}/progress", token=token)
            if code == 200 and last.get("status") in ("awaiting_confirmation", "completed", "failed"):
                break
            await asyncio.sleep(2)

        seen_processed.append(int(last.get("processed_rows") or 0))
        if expected < slice_count:
            checker.check(
                f"第 {expected} 片跑完停在 awaiting_confirmation",
                last.get("status") == "awaiting_confirmation",
                f"status={last.get('status')} processed={last.get('processed_rows')}/{last.get('total_rows')}",
            )
        else:
            checker.check(
                "最后一片跑完 completed 且 100%",
                last.get("status") == "completed"
                and int(last.get("processed_rows") or 0) == int(last.get("total_rows") or 0),
                f"status={last.get('status')} {last.get('processed_rows')}/{last.get('total_rows')}",
            )
        if last.get("status") == "failed":
            checker.check("未出现 failed", False, json.dumps(last, ensure_ascii=False)[:200])
            break

    checker.check(
        "进度只增不减",
        seen_processed == sorted(seen_processed),
        f"逐片 processed={seen_processed}",
    )

    # 5) 最终工单状态 —— 必须**等阶段 8 收尾**再读 stats（见 `wait_for_aggregation`）
    code, detail = await wait_for_aggregation(base, token, job_id, args.agg_timeout)
    final_stats = (detail.get("stats") or {}) if code == 200 else {}
    aggregate = final_stats.get("aggregate") or {}
    checker.check(
        "阶段 8 聚合成功（不是「跑过就算」——75 组全失败也算跑过）",
        bool(aggregate) and not aggregate.get("skipped") and not aggregate.get("failed"),
        json.dumps(
            {k: aggregate.get(k) for k in ("groups", "ok", "failed", "postings", "elapsed_s")},
            ensure_ascii=False,
        )
        + f" errors={str(aggregate.get('errors') or [])[:200]}",
    )

    # 5.5) **静默降级守卫**：各 LLM 工具调用失败时会"返回骨架值、让流水线继续跑"，
    #      于是导入照样报 completed —— 这是本链路最危险的一类失败。
    #      实测 2026-10-04：网关照 DB 配置后，未绑定的功能键**不会**回退 env 的
    #      `LLM_DEFAULT_MODEL`（2026-09-25 决策②）→ 抽取/画像/聚合全拿到
    #      `LLMGatewayError: 未配置默认模型`：524 行"导入成功"、47 条画像的六维却全是
    #      默认的 `{"score": 3}`、`payload.extract` 全空、75 个聚合组 0.4 秒内全失败。
    #      所以这里必须显式断言失败计数为 0。
    #      ⚠️ `stats.<key>` 记的是**最后一片**（切片模式下不做跨片累计），能抓到"整链路挂了"
    #      但抓不到"只有中间某一片挂了"。
    portrait_stats = final_stats.get("portrait") or {}
    persist_stats = final_stats.get("persist") or {}
    first_portrait_error = (portrait_stats.get("errors") or ["-"])[0]
    checker.check(
        "没有静默降级：画像/落库失败数为 0（失败会退成骨架值却仍报成功）",
        not portrait_stats.get("failed") and not persist_stats.get("failed"),
        f"portrait.failed={portrait_stats.get('failed')} "
        f"persist.failed={persist_stats.get('failed')}（仅最后一片）"
        f" 首个画像错误：{str(first_portrait_error)[:120]}",
    )

    # ── 本次导入的作用域与计数（后面所有 DB 断言都依赖它们）──────────────────────
    # ⚠️ **不能按"验收前缀"过滤岗位名**：`--full` 导的是真实表，岗位名是 "APP推广"
    # 这类真实词、一个都不带前缀 → 按标题过滤会读到 0 行，下面所有 DB 断言**全部假失败**。
    #   ① 原始行：用导入前的 `max(id)` 水位圈（`job_raw_data` 不回写 job_id）；
    #   ② 岗位画像：用 `stats.slices.touched_titles`（`title_key`，跨片累计）。
    touched = [str(k) for k in ((final_stats.get("slices") or {}).get("touched_titles") or [])]
    cumulative = (final_stats.get("slices") or {}).get("cumulative") or {}
    passed_total = int(cumulative.get("passed") or final_stats.get("success_count") or 0)
    rejected_total = int(cumulative.get("rejected") or final_stats.get("error_count") or 0)
    checker.note(
        f"作用域：job_raw_data.id > {raw_marker}；job_profiles 命中 {len(touched)} 个 title_key；"
        f"质检累计通过 {passed_total} / 拒绝 {rejected_total}"
    )

    # 5.5) B3/事故 A 的**确定性**证据：切片模式下流水线必须读满每一片。
    #      旧实现 `IMPORT_MAX_ROWS=100` 把 524 行只读前 100 行 —— 事故 A 的第一根因。
    #      切片模式下 `nrows=None`（片大小本身就是闸门），所以逐片 `total_input` 之和
    #      必须**正好等于**上传行数；任何截断都会让这个数变小。
    checker.check(
        "B3 流水线读满了每一片（没有 IMPORT_MAX_ROWS 二次截断）",
        int(cumulative.get("rows") or 0) == total_rows,
        f"逐片 total_input 累计 {cumulative.get('rows')} / 清单总行数 {total_rows}"
        f"（--full 时与 --rows 无关，以 manifest 为准）",
    )

    # 6) 落库校验（DB）
    raw_count = await count_sql(
        "SELECT count(*) FROM job_raw_data WHERE id > :raw_marker", {"raw_marker": raw_marker}
    )
    checker.check("原始数据已落库", raw_count >= 1, f"job_raw_data = {raw_count} 行")

    payload_rows = await fetch_rows(
        "SELECT payload FROM job_raw_data WHERE id > :raw_marker AND payload IS NOT NULL LIMIT 5",
        {"raw_marker": raw_marker},
    )
    checker.check(
        "payload 已落库且含 extract/source（聚合的数据来源）",
        bool(payload_rows) and all(("extract" in r[0] or "source" in r[0]) for r in payload_rows),
        f"{len(payload_rows)} 行有 payload",
    )

    profile_rows = await fetch_rows(
        "SELECT title, level, salary_stats, aggregate_card, requirement_intensity, hard_skills "
        "FROM job_profiles WHERE title_key = ANY(:keys)",
        {"keys": touched},
    )
    checker.check("岗位画像已落库", len(profile_rows) >= 1, f"job_profiles = {len(profile_rows)} 条")

    if profile_rows:
        pairs = {(row[0], row[1]) for row in profile_rows}
        checker.check(
            "唯一键是 (岗位名, 等级)：同名不同等级 = 多条",
            len(pairs) == len(profile_rows),
            f"组合 {sorted(pairs)}",
        )
        checker.check(
            "每条画像都带等级（非空）",
            all(row[1] for row in profile_rows),
            f"等级取值 {sorted({row[1] for row in profile_rows})}",
        )
        with_salary = [row for row in profile_rows if isinstance(row[2], dict)]
        checker.check(
            "salary_stats 两者都存（包络 + 中位数）",
            bool(with_salary) and all("envelope" in r[2] and "median" in r[2] for r in with_salary),
            f"{len(with_salary)}/{len(profile_rows)} 条有 salary_stats",
        )
        with_card = [row for row in profile_rows if isinstance(row[3], dict)]
        checker.check(
            "aggregate_card 落库且含 excluded_noise（可审计）",
            bool(with_card) and all("excluded_noise" in r[3] for r in with_card),
            f"{len(with_card)}/{len(profile_rows)} 条有综合卡",
        )
        six_ok = []
        for row in profile_rows:
            intensity = row[4] if isinstance(row[4], dict) else {}
            six_ok.append(
                {"专业技术能力", "实践经验背景", "通用软素质", "职业匹配度", "成长潜力", "基础资质条件"}
                <= set(intensity.keys())
            )
        checker.check("画像六维齐全", all(six_ok), f"{sum(six_ok)}/{len(six_ok)} 条齐全")

        # B5：技能已归一化
        bad_skills: list[str] = []
        over_limit = False
        for row in profile_rows:
            hard = row[5] if isinstance(row[5], dict) else {}
            tags = hard.get("tags") or []
            if len(tags) > CORE_SKILL_LIMIT:
                over_limit = True
            bad_skills += [t for t in tags if t in ("Java开发", "MySQL数据库", "springboot")]
        checker.check("技能已归一化（不出现带修饰的写法）", not bad_skills, f"异常项 {bad_skills[:5]}")
        checker.check("核心技能 ≤ 20", not over_limit)

    # 7) B1：城市纯化 + 薪资量级
    dirty_city = await count_sql(
        "SELECT count(*) FROM job_raw_data WHERE id > :raw_marker AND city LIKE '%-%'",
        {"raw_marker": raw_marker},
    )
    checker.check("B1 城市是纯城市名（不含 `-`）", dirty_city == 0, f"脏城市 {dirty_city} 行")

    # `salary ~ '^[0-9]+-'` 是必需的：真实表里有「面议」这类非数值薪资，
    # 直接 `CAST(split_part(salary,'-',1) AS INTEGER)` 会**报错中断整轮验收**
    # （实测："面议" → invalid input syntax for type integer）。
    weird_salary = await count_sql(
        "SELECT count(*) FROM ("
        "  SELECT CAST(split_part(salary, '-', 1) AS INTEGER) AS lo FROM job_raw_data"
        "  WHERE id > :raw_marker AND salary ~ '^[0-9]+-'"
        ") s WHERE lo < :floor",
        {"raw_marker": raw_marker, "floor": 100},
    )
    checker.check(
        "B1 薪资是月薪量级（没有 `1.2-1.3万` 被 ÷12 的 1000 档）",
        weird_salary == 0,
        f"异常低价 {weird_salary} 行（阈值 <100 元/月）",
    )
    checker.check(
        "B1 薪资阈值合理（ABS_JUNIOR_MAX 已生效）",
        ABS_JUNIOR_MAX == 6000,
        f"ABS_JUNIOR_MAX={ABS_JUNIOR_MAX}",
    )

    # 8) B2：同名同公司但编码不同的行**一条都没少**
    #
    # 两条**互相独立**的证据，缺一不可：
    #   ① 去重阶段自报（确定性，不依赖 LLM）：没有任何一行走 `(岗位名, 公司)` 那一级被并掉；
    #   ② 端到端：上传的每一行都落进了 `job_raw_data`（去重没吞、质检也没收）。
    # 为什么必须拆开：质检是 **LLM** 判的 —— 行写得薄就判 D 丢掉（实测 12 行样本被拒 9 行）。
    # 那是质检的收放，不是去重把数据并没了；混进同一个断言会把排查指向错误的方向。
    dedup_stats = final_stats.get("dedup") or {}
    if dedup_stats:
        # `title_company_removed` 是**事故本体**：旧实现把"同名同公司但编码各异"的行并成 1 行。
        # `identity_removed` 只在**小样本**上要求为 0 —— 真实表 524 行里 `岗位编码` 只有
        # 487 个唯一值，**同一个编码在一张表里重复出现是正常的**（同一岗位的多次发布），
        # 被去掉才是对的；拿它当断言会在 `--full` 上假失败（实测）。
        identity_ok = not args.full or int(dedup_stats.get("identity_removed") or 0) == 0
        checker.check(
            "B2 去重只按唯一标识、没有走 (岗位名, 公司) 并行",
            int(dedup_stats.get("title_company_removed") or 0) == 0 and identity_ok,
            f"input={dedup_stats.get('input')} kept={dedup_stats.get('kept')} "
            f"identity_removed={dedup_stats.get('identity_removed')} "
            f"title_company_removed={dedup_stats.get('title_company_removed')}"
            "（注：stats.dedup 记的是**最后一片**，切片模式下不做跨片累计）",
        )

    if not args.full:
        distinct_codes = await count_sql(
            "SELECT count(DISTINCT payload->'source'->>'code') FROM job_raw_data "
            "WHERE id > :raw_marker AND payload->'source'->>'code' IS NOT NULL",
            {"raw_marker": raw_marker},
        )
        checker.note(f"落库不同编码 {distinct_codes} 个")
        # ⚠️ **不**断言 `raw_count == args.rows`：质检是 LLM 判的，判分有波动
        # （实测 12 行样本会被拒 1 行，理由还提到"岗位名称带有系统导入残留"——
        # 样本标题本就是给测试用的）。"上传多少就落多少"这件事由上面两条**确定性**
        # 证据覆盖（逐片 total_input 累计 == 上传行数；去重阶段没走名称合并）；
        # 这里只兜一个常识性下限：样本是照着合格招聘写的，不该被大面积判 D。
        checker.check(
            "小样本绝大多数行通过质检（样本本身就是合格招聘）",
            passed_total >= args.rows - 3,
            f"质检通过 {passed_total}/{args.rows}（LLM 判分有波动，留 3 行余量）",
        )

    # 两种模式共用的落库完整性：通过质检的行**一行都不能在落库路上丢**。
    # （`--full` 里"上传行数"没有意义：真实表本来就有跨片重复编码，
    #   逐片去重看不到全局，所以只比"通过质检的行"与"真写进 raw 的行"。）
    checker.check(
        "B2 通过质检的行全部落库（落库行数 == 质检通过数）",
        raw_count == passed_total,
        f"落库 {raw_count} 行 / 质检通过 {passed_total} / 拒绝 {rejected_total}",
    )

    # 9) 幂等：重跑聚合，profile 数量不变
    if aggregate and not aggregate.get("failed"):
        from app.domain.services.job_aggregate_service import aggregate_roles

        titles = set(touched) or {row[0].lower() for row in profile_rows}
        before = len(profile_rows)
        async with async_session_factory() as session:
            again = await aggregate_roles(session, titles=titles)
        after = await count_sql(
            "SELECT count(*) FROM job_profiles WHERE title_key = ANY(:keys)",
            {"keys": list(titles)},
        )
        checker.check(
            "聚合幂等（重跑不新增画像）",
            after == before and not again.get("failed"),
            f"{before} → {after}；重跑 ok={again.get('ok')} failed={again.get('failed')}",
        )

    await cleanup(username, args.keep, job_ids, full=args.full)
    _ = shutil  # 保留 import 以便将来清理临时目录
    return checker.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入流水线端到端验收（B1–B5）")
    parser.add_argument(
        "--base",
        default="http://127.0.0.1:8001",
        help="后端地址（默认是**容器内** uvicorn 端口；宿主上请用 http://127.0.0.1:8002）",
    )
    parser.add_argument("--rows", type=int, default=12, help="小样本行数（默认 12）")
    parser.add_argument("--full", action="store_true", help="跑真实 524 行文件（约 25 分钟、660 次 LLM）")
    parser.add_argument("--keep", action="store_true", help="保留现场不清理")
    parser.add_argument("--slice-timeout", type=int, default=600, help="单片最长等待秒数")
    parser.add_argument(
        "--agg-timeout",
        type=int,
        default=1800,
        help="最后一片跑完后等阶段 8 聚合收尾的最长秒数（真实 87 组约几分钟）",
    )
    args = parser.parse_args(argv)

    checker = Checker()
    try:
        return asyncio.run(run(args, checker))
    except Exception as exc:  # noqa: BLE001 - 验收脚本要把异常变成可见的失败
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
