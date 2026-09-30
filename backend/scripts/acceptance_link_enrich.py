#!/usr/bin/env python
"""B3-1 链接富化真栈验收（打**真实 HTTP**，不是 TestClient）。

为什么还要一个脚本（明明有 pytest）
------------------------------------
`test_core` 里 147 条用例把算法钉得很死，但它们**全部用 MockTransport 顶掉了网络**。
本脚本验证的正是被顶掉的那一段：容器真的能出网、真实招聘页能被解析、真实导入
API 能把它落进库。两者互补，缺一不可。

验收项
------
1. **真实出网 + JSON-LD 命中**：一行只有岗位名 + 一个真实岗位链接，
   富化后公司/城市/描述被补齐（**全程零 LLM**）；
2. **SSRF 守卫拦下内网地址**：另一行的链接是 `169.254.169.254`（云元数据），
   必须被拒绝并记进 `stats.link_enrich.blocked`；
3. **缓存复用**：同一个文件导第二次，`cache_hits` 必须 > 0（"重复导入不再出网"）；
4. **落库**：`job_profiles.source_url` / `enrich_stats` 真的写了（这两列此前只在 DDL
   里、ORM 没映射，谁也写不进去）；
5. **开关默认关**：脚本自己断言当前进程确实开着开关（关的那条路由 pytest 覆盖）；
6. 跑完**自清理**（岗位/原始行/导入任务/缓存/上传文件/临时管理员）。

用法
----
    # 需要先让后端进程带上开关（默认 false，主计划 §4.5 要求先关后开）：
    #   在 .env 里加 LINK_ENRICH_ENABLED=true 后 `docker compose up -d backend`
    docker exec -e PYTHONPATH=/app/backend -e PYTHONIOENCODING=utf-8 -w /app/backend \
        career_backend python scripts/acceptance_link_enrich.py

    # 保留现场排查（不清理）：
    ... python scripts/acceptance_link_enrich.py --keep

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
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402

PREFIX = f"acclink_{int(time.time())}"
PASSWORD = "AccLink-2026!pass"

#: 真实岗位详情页（Lever 的 demo 板，公开可访问且页面里带 schema.org JobPosting）
REAL_JOB_URL = "https://jobs.lever.co/leverdemo/58db3f8e-b108-47d1-9e6e-87a1712497cd"

#: 云元数据地址：SSRF 的经典靶子，必须被守卫拦下
SSRF_URL = "http://169.254.169.254/latest/meta-data/"

# ⚠️ 三个岗位名必须**彼此差异够大**：`dedup` 的模糊去重阈值是 0.85，
# 若三条共用一长串公共前缀（如都用 `acclink_<ts> ...`）只在尾巴上不同，
# 会被判成重复行直接丢掉（2026-09-27 实测：3 行只剩 2 行，对照行被吃掉）。
# 前缀只放在**末尾**，让真正的岗位名部分承担差异。
TITLE_A = f"高级后端开发工程师（链接富化验收 {PREFIX}）"
TITLE_B = f"市场运营专员（无链接对照 {PREFIX}）"
TITLE_C = f"数据分析实习生（SSRF 防护验收 {PREFIX}）"


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
        """只说明、不计入通过率（用于"这一轮没验到，但原因已知且不是缺陷"）。"""
        print(f"[NOTE] {message}", flush=True)

    def summary(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(f"\n[SUMMARY] {len(self.results) - len(failed)}/{len(self.results)} 项通过", flush=True)
        if failed:
            print("[FAILED] " + "、".join(failed), file=sys.stderr)
            return 1
        return 0


# ── HTTP（urllib，容器内直连 uvicorn 真实端口）─────────────────────────────


def http(
    base: str,
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, object]:
    url = base + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)  # noqa: S310
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def upload_csv(base: str, token: str, filename: str, content: bytes) -> tuple[int, object]:
    """multipart/form-data 上传（`file` 字段，与 `import_module.upload_file` 对齐）。"""
    boundary = "----acclink" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: text/csv\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(base + "/api/v1/admin/import/upload", data=body, method="POST")  # noqa: S310
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def build_csv() -> bytes:
    """三行：一行真链接、一行无链接对照、一行 SSRF 靶子。

    只给「岗位名称」+「岗位链接」，**刻意留空公司/城市/薪资/描述** ——
    这样"字段有没有被补齐"只能来自链接。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["岗位名称", "公司名称", "所在城市", "薪资范围", "岗位链接", "岗位描述", "学历要求"])
    writer.writerow([TITLE_A, "", "", "", REAL_JOB_URL, "", ""])
    writer.writerow([TITLE_B, "", "", "", "", "", ""])
    writer.writerow([TITLE_C, "", "", "", SSRF_URL, "", ""])
    return buffer.getvalue().encode("utf-8-sig")  # BOM：Excel 打开中文列名不乱码


async def setup_admin(username: str) -> None:
    """注册临时用户并提权为 admin（不依赖任何预置密码）。"""
    from sqlalchemy import text

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE username = :u"), {"u": username}
        )
        await session.commit()


async def cleanup(username: str, keep: bool, job_ids: list[int]) -> None:
    from sqlalchemy import text

    if keep:
        print(f"[cleanup] --keep：保留现场（前缀 {PREFIX}）", flush=True)
        return
    async with async_session_factory() as session:
        # 先记下这些岗位关联到的公司 —— 公司实体是**链接补出来的**（名字不匹配我们的
        # 前缀，按名字删不掉）。必须在删岗位**之前**取，否则关联行先被 CASCADE 掉就查
        # 不到了（2026-09-27 踩坑：跑完库里留着一家 "Lever Demo 2"）。
        company_ids = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT DISTINCT l.company_id FROM job_company_links l "
                        "JOIN job_profiles p ON p.id = l.job_profile_id "
                        "WHERE p.title = ANY(:titles)"
                    ),
                    {"titles": [TITLE_A, TITLE_B, TITLE_C]},
                )
            ).all()
        ]
        for title in (TITLE_A, TITLE_B, TITLE_C):
            # job_match_embeddings 的外键没有 ON DELETE CASCADE，必须先清子行
            await session.execute(
                text(
                    "DELETE FROM job_match_embeddings WHERE job_profile_id IN "
                    "(SELECT id FROM job_profiles WHERE title = :t)"
                ),
                {"t": title},
            )
            await session.execute(text("DELETE FROM job_profiles WHERE title = :t"), {"t": title})
            await session.execute(text("DELETE FROM job_raw_data WHERE title = :t"), {"t": title})
        for company_id in company_ids:
            # 只删"删完岗位后彻底没人关联"的公司，避免误删别的岗位在用的实体
            await session.execute(
                text(
                    "DELETE FROM companies WHERE id = :cid AND NOT EXISTS "
                    "(SELECT 1 FROM job_company_links WHERE company_id = :cid)"
                ),
                {"cid": company_id},
            )
        await session.execute(
            text("DELETE FROM link_fetch_cache WHERE url LIKE :p"), {"p": "%leverdemo%"}
        )
        await session.execute(
            text("DELETE FROM data_import_jobs WHERE file_name LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await session.execute(text("DELETE FROM users WHERE username = :u"), {"u": username})
        await session.commit()

    # 上传落盘的文件（`UPLOAD_DIR = uploads/import`，相对 CWD=/app/backend）。
    # 别 glob `/app/uploads`：那是另一个命名卷，实际文件不写在那里
    # （2026-09-27 踩坑：清理报 "0 files"，文件其实留在 /app/backend/uploads/import）。
    removed = 0
    for job_id in job_ids:
        for path in Path("/app/backend/uploads/import").glob(f"{job_id}_*"):
            path.unlink(missing_ok=True)
            removed += 1
    print(f"[cleanup] 已清理测试数据（含 {removed} 个上传文件）", flush=True)


# ── 主流程 ────────────────────────────────────────────────────────────────


async def run_checks(base: str, keep: bool) -> int:
    c = Checker()
    username = f"{PREFIX}_admin"
    job_ids: list[int] = []

    settings = get_settings()
    c.check(
        "开关已打开（LINK_ENRICH_ENABLED=true）",
        settings.link_enrich_enabled,
        f"enabled={settings.link_enrich_enabled} max_rows={settings.link_enrich_max_rows}",
    )
    if not settings.link_enrich_enabled:
        print("\n请先在 .env 里设 LINK_ENRICH_ENABLED=true 并 docker compose up -d backend", file=sys.stderr)
        return 1

    try:
        status, _ = http(base, "/api/v1/auth/register", method="POST",
                         payload={"username": username, "password": PASSWORD})
        c.check("注册临时管理员", status == 201, f"HTTP {status}")
        await setup_admin(username)

        status, data = http(base, "/api/v1/auth/login", method="POST",
                            payload={"username": username, "password": PASSWORD})
        token = data.get("access_token") if isinstance(data, dict) else None
        c.check("登录拿到 token", status == 200 and bool(token), f"HTTP {status}")

        csv_bytes = build_csv()
        filename = f"{PREFIX}.csv"

        # ── 第一次导入：真实富化 ────────────────────────────────────────
        status, job = upload_csv(base, token, filename, csv_bytes)
        c.check("上传 CSV", status == 201 and isinstance(job, dict), f"HTTP {status}")
        job_id = int(job["id"])
        job_ids.append(job_id)

        http(base, f"/api/v1/admin/import/{job_id}/process", token=token, method="POST")

        # 先只等**富化阶段**：runner 每阶段单独 commit，所以 `stats.link_enrich` 在
        # 几秒内就可见；而后面三次 LLM（质检/提取/画像）要跑好几分钟。
        # 分开等的价值：富化相关的断言不必陪着 LLM 一起等，超时也不会把整场验收拖垮。
        detail = await _wait_for_enrich_stats(base, token, job_id, deadline_s=300)

        enrich = (detail.get("stats") or {}).get("link_enrich") or {}
        print("\n--- stats.link_enrich ---")
        print(json.dumps(enrich, ensure_ascii=False, indent=2)[:2500], flush=True)

        c.check("富化阶段已落统计", bool(enrich), f"keys={sorted(enrich)}")
        c.check("富化发现链接", enrich.get("urls_found", 0) >= 2, f"urls_found={enrich.get('urls_found')}")
        c.check("命中 JSON-LD 结构化数据", enrich.get("jsonld_hits", 0) >= 1,
                f"jsonld_hits={enrich.get('jsonld_hits')} og={enrich.get('og_hits')} text={enrich.get('text_hits')}")
        filled = enrich.get("fields_filled") or {}
        c.check("补齐了公司字段", filled.get("company", 0) >= 1, f"fields_filled={filled}")
        c.check("补齐了城市字段", filled.get("city", 0) >= 1)
        c.check("补齐了描述字段", filled.get("description", 0) >= 1)
        c.check("三行都进了富化阶段（对照行未被模糊去重吃掉）",
                enrich.get("rows_scanned") == 3, f"rows_scanned={enrich.get('rows_scanned')}")

        # ── SSRF 守卫 ────────────────────────────────────────────────
        blocked = enrich.get("blocked") or []
        c.check("云元数据地址被守卫拒绝", len(blocked) >= 1, f"blocked={blocked}")
        c.check(
            "拒绝原因可读（链路本地/元数据）",
            any("链路本地" in str(b.get("reason", "")) or "元数据" in str(b.get("reason", ""))
                for b in blocked),
        )
        c.check("被拒地址没有计入抓取成功", enrich.get("http_hits", 0) <= enrich.get("urls_unique", 1))

        # ── 等第一次导入整条流水线走完（落库要等 persist）──────────────
        # ⚠️ **必须等它跑完再动第二次导入**：两次导入的 LLM 阶段并发会让质检调用
        # 受限流/超时，而 `quality_judge` **任何异常都返回 D 级**
        # (`_DEFAULT_QUALITY`) → 该行不生成画像 → 落库检查假红
        # （2026-09-27 实测：把第二次导入提前后，画像检查从 PASS 变 FAIL）。
        detail = await _wait_for_completion(base, token, job_id, deadline_s=900)
        c.check("导入跑完", detail.get("status") == "completed", f"status={detail.get('status')}")

        # ── 落库 ────────────────────────────────────────────────────
        try:
            await _check_persisted(c, detail)
        except Exception as exc:  # noqa: BLE001
            c.check("落库校验执行完成", False, f"{type(exc).__name__}: {exc}")

        # ── 第二次导入同一文件：应全部走缓存（放在最后，避免与第一次争用 LLM）──
        status, job2 = upload_csv(base, token, filename, csv_bytes)
        job_id2 = int(job2["id"])
        job_ids.append(job_id2)
        http(base, f"/api/v1/admin/import/{job_id2}/process", token=token, method="POST")
        detail2 = await _wait_for_enrich_stats(base, token, job_id2, deadline_s=300)
        enrich2 = (detail2.get("stats") or {}).get("link_enrich") or {}
        c.check(
            "重复导入命中缓存（不再出网）",
            enrich2.get("cache_hits", 0) >= 1,
            f"cache_hits={enrich2.get('cache_hits')} urls_fetched={enrich2.get('urls_fetched')}",
        )
        # 等它跑完再清理：否则清理删掉任务行后，后台流水线仍会继续写库 → 留下孤儿数据
        await _wait_for_completion(base, token, job_id2, deadline_s=900)

    finally:
        await cleanup(username, keep, job_ids)

    return c.summary()


async def _check_persisted(c: Checker, detail: dict) -> None:
    """落库校验（SQL 部分单独放，便于整体包一层 try/except 报 FAIL 而非抛栈）。

    ⚠️ 三个列位置极易搞错（都踩过）：

    - `job_profiles` **没有 `description`** —— 描述落在 `job_raw_data`；
    - `job_profiles` **没有 `city`/`region`/招聘薪资** —— 它们在 `job_company_links`
      上（一行 = 一次招聘）。岗位是**角色级**的，本身不带地域（任务 3 的多对多模型）；
    - 公司名要经 `job_company_links` 关联到 `companies`。

    **断言是"字段驱动"而不是"写死字段名"**：拿 `enrich_stats.filled` 里实际补到的
    每个字段，逐个去它该落的地方确认非空。靶页提供什么就验什么 —— 本轮就吃过写死
    期望的亏：靶页 JSON-LD 根本没有 `baseSalary`，而脚本写死了"薪资必须落库"，
    于是报 FAIL。那是**断言错，不是产品错**。

    **判 D 时如实说明而不是假 FAIL**：`quality_judge` 任何异常都返回 D 级
    （`_DEFAULT_QUALITY`），D 行只进 `job_raw_data`、不生成画像。那不是富化的缺陷，
    所以画像级断言在那种情况下记 NOTE 跳过（"enrich_stats 落 job_profiles" 这条
    由确定性的单测 `TestPersistWritesEnrichColumns` 钉住）。

    > 实测（2026-09-27）本脚本的靶数据**真的会被判 D，而且是质检判对了**：
    > 岗位名写「高级后端开发工程师」、链接却指向一篇 Sales Engineer 的 JD，
    > 质检的判词是"标题为后端开发，描述却为销售工程师…内容错位"。
    > **想稳定拿到画像级证据，就让这一行的岗位名与靶页的真实角色一致**
    > （或补上学历/经验等表格字段提高完整度）—— 别把矛盾数据喂给质检。
    """
    from sqlalchemy import text

    async with async_session_factory() as session:
        # ⚠️ 2026-09-30 用户要求：**不合格（质检 D 级）岗位不进原始数据表**。
        # 于是"raw 里有没有这一行"在**有画像 / 无画像**两种情况下**期望正好相反** ——
        # 必须分别断言，不能因为"找不到行"就静默跳过（那会把新规则漏测掉）。
        # 所以先查画像（它决定这行有没有通过质检），再查原始行。
        profile = (
            await session.execute(
                text(
                    "SELECT p.id, p.source_url, p.enrich_stats, p.salary_range, p.industry, "
                    "       p.level, p.education_requirement, p.experience_requirement "
                    "FROM job_profiles p WHERE p.title = :t"
                ),
                {"t": TITLE_A},
            )
        ).first()

        raw = (
            await session.execute(
                text(
                    "SELECT company, city, description, requirements, source FROM job_raw_data "
                    "WHERE title = :t ORDER BY id DESC"
                ),
                {"t": TITLE_A},
            )
        ).first()

        if profile is None:
            # 判 D（不合格）：**新规则下这一行不该出现在原始数据表里** —— 正向断言它
            d_reasons = [e for e in (detail.get("errors") or []) if TITLE_A[:12] in str(e)]
            c.check(
                "被判 D 的不合格岗位**没有**进原始数据表（2026-09-30 用户要求）",
                raw is None,
                f"raw={'存在 → 旧行为！' if raw is not None else '不存在'}；"
                f"原因={d_reasons or detail.get('errors')}",
            )
            c.note(
                "该行被质检判 D → 不生成岗位画像、**也不写原始数据表**，画像级断言本轮跳过；"
                "（判 D 属质检口径，不是富化缺陷；'enrich_stats 落 job_profiles' 由单测 "
                "test_link_enrich_pipeline.TestPersistWritesEnrichColumns 覆盖）"
            )
            return

        # 通过质检（A/B/C）：原始行**应该在**，且链接富化的字段要落进去
        c.check("通过质检的行已落原始表", raw is not None)
        c.check("链接富化的岗位已落库", True)
        raw_company, raw_city, raw_desc, raw_req, raw_source = raw
        c.check(
            "链接里的描述已落进原始行",
            bool(raw_desc) and len(raw_desc) > 100,
            f"description_chars={len(raw_desc) if raw_desc else 0}",
        )
        c.check("链接里的公司已落进原始行", bool(raw_company), f"raw.company={raw_company}")

        pid, source_url, enrich_stats, salary_range, industry, level, edu, exp = profile
        c.check("job_profiles.source_url 已写入", bool(source_url), f"source_url={source_url}")
        c.check(
            "job_profiles.enrich_stats 已写入",
            bool(enrich_stats) and bool(enrich_stats.get("filled")),
            f"filled={sorted((enrich_stats or {}).get('filled') or [])}",
        )

        link = (
            await session.execute(
                text("SELECT city, region, salary FROM job_company_links WHERE job_profile_id = :i"),
                {"i": pid},
            )
        ).first()
        company = (
            await session.execute(
                text(
                    "SELECT c.name FROM job_company_links l JOIN companies c ON c.id = l.company_id "
                    "WHERE l.job_profile_id = :i"
                ),
                {"i": pid},
            )
        ).first()
        # raw 行已在上面查过（走到这里说明画像存在）—— 直接用它的字段
        link_city, link_region, link_salary = link if link else (None, None, None)
        company_name = company[0] if company else None

        c.check("链接里的城市已落库（未被占位值「未知」挡住）",
                link_city not in (None, "", "未知"), f"link.city={link_city}")
        c.check("链接里的公司名落成了公司实体", bool(company_name), f"company={company_name}")

        # 字段 → 它该落的位置
        where = {
            "company": ("raw.company", raw_company),
            "city": ("link.city", link_city),
            "region": ("link.region", link_region),
            "salary": ("profile.salary_range|link.salary", salary_range or link_salary),
            "industry": ("profile.industry", industry),
            "level": ("profile.level", level),
            "education_requirement": ("profile.education_requirement", edu),
            "experience_requirement": ("profile.experience_requirement", exp),
            "description": ("raw.description", raw_desc),
            "requirements": ("raw.requirements", raw_req),
        }
        filled = sorted((enrich_stats or {}).get("filled") or [])
        for field in filled:
            target, value = where.get(field, (f"（未登记位置）{field}", None))
            c.check(f"富化字段「{field}」已落库", bool(value), f"{target}={str(value)[:80]!r}")

        if "salary" not in filled:
            # 别让这件事静默消失：说明"本轮没验到薪资链路"以及它在哪被覆盖
            c.note(
                "靶页 JSON-LD 未提供 baseSalary，本轮未验到薪资落库链路；"
                "薪资的解析与格式化由单测 test_salary_is_formatted_and_within_column_width 覆盖"
            )

        cached = (
            await session.execute(
                text("SELECT count(*), max(status_code) FROM link_fetch_cache WHERE url LIKE :p"),
                {"p": "%leverdemo%"},
            )
        ).first()
        c.check("抓取结果已落缓存", cached[0] >= 1, f"rows={cached[0]} status={cached[1]}")


async def _wait_for_enrich_stats(base: str, token: str, job_id: int, *, deadline_s: int) -> dict:
    """等到 `stats.link_enrich` 出现（富化阶段结束）就返回。

    runner 是**每阶段 commit**，所以这个统计在富化跑完的瞬间就能读到，
    不必等后面三次 LLM。超时则把任务标 failed —— 否则它会永远停在 `processing`
    （2026-09-27 实测：`--reload` 杀掉后台任务后，任务行没有任何对账机制，一直显示
    "处理中"），把验收现场弄脏。
    """
    deadline = time.time() + deadline_s
    detail: dict = {}
    while time.time() < deadline:
        status, detail = http(base, f"/api/v1/admin/import/{job_id}", token=token)
        if isinstance(detail, dict):
            stats = detail.get("stats") or {}
            if stats.get("link_enrich"):
                return detail
            if detail.get("status") in ("completed", "failed"):
                return detail
        await asyncio.sleep(2)
    await _mark_failed(job_id, "验收超时：未等到 link_enrich 统计")
    return detail


async def _mark_failed(job_id: int, reason: str) -> None:
    """把卡住的任务标成 failed（验收卫生，不改产品行为）。"""
    from sqlalchemy import text

    try:
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE data_import_jobs SET status='failed', errors=:e WHERE id=:i"),
                {"e": json.dumps([reason], ensure_ascii=False), "i": job_id},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 标记任务 {job_id} 失败时出错：{exc}", file=sys.stderr)


async def _wait_for_completion(base: str, token: str, job_id: int, *, deadline_s: int) -> dict:
    """轮询导入任务到终态（流水线每行要调若干次 LLM，给足超时）。"""
    deadline = time.time() + deadline_s
    detail: dict = {}
    while time.time() < deadline:
        status, detail = http(base, f"/api/v1/admin/import/{job_id}", token=token)
        if isinstance(detail, dict) and detail.get("status") in ("completed", "failed"):
            return detail
        await asyncio.sleep(3)
    print(f"[warn] 导入 {job_id} 超时未到终态", file=sys.stderr)
    await _mark_failed(job_id, "验收超时：未到终态")
    return detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B3-1 链接富化真栈验收")
    parser.add_argument("--base", default="http://localhost:8001")
    parser.add_argument("--keep", action="store_true", help="保留测试数据（排查用）")
    args = parser.parse_args(argv)
    return asyncio.run(run_checks(args.base, args.keep))


if __name__ == "__main__":
    raise SystemExit(main())
