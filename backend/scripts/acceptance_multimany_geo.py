#!/usr/bin/env python
"""任务 5 真栈验收：岗位 ↔ 公司**多对多** + **省市级联**（打**真实 HTTP**，不是 TestClient）。

为什么还要一个脚本（明明有 pytest）
------------------------------------
`test_api` 走的是进程内 `TestClient`，它**绕过了** nginx / uvicorn / 真实网络与真实启动参数。
本脚本**在容器里**跑，用 urllib 打 `http://localhost:8001`（容器内 uvicorn 的真实端口）
→ 覆盖的就是"用户实际会碰到的那个栈"。两者互补，缺一不可。

验收项（对应计划 §26 / §22.5 的任务 5）
--------------------------------------
1. **删公司 204 回归**（核心）：两家公司招同一岗位 → 删第二家**必须是 204**。
   P2 时代这里是 **500**（`company_id` 上的 `ON DELETE SET NULL` + 把该列当身份的唯一索引
   → `duplicate key ... (title, null)`）；任务 3 删列后这条路径结构上不存在；
2. **地域端到端**：导入写官方全名「广东省/深圳市」→ 库里落**短名**「广东/深圳」
   → 用短名按 `coalesce(关联行, 公司)` 筛**命中**；级联选项里也必须有它；
3. 岗位详情的「在招公司」带上 `region/scale/salary/source_url`；
4. **删岗位 204 回归**（§18：清 embedding 子行 + 追平 `job_count`，否则 500）；
5. 跑完**自清理**（按前缀删），不留测试数据。

用法
----
    # 容器内（唯一支持的方式：脚本 import app.*）
    docker exec -e PYTHONPATH=/app/backend -e PYTHONIOENCODING=utf-8 -w /app/backend \
        career_backend python scripts/acceptance_multimany_geo.py

    # 保留现场排查（不清理）
    ... python scripts/acceptance_multimany_geo.py --keep

退出码：0 = 全通过；1 = 有失败项（CI/人工都能直接用）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PREFIX = f"acc5_{int(time.time())}"

#: 用**官方全名**写库，专门验证"写路径会归一化成短名"
IMPORT_REGION, IMPORT_CITY = "广东省", "深圳市"
EXPECT_REGION, EXPECT_CITY = "广东", "深圳"


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

    def summary(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(f"\n[SUMMARY] {len(self.results) - len(failed)}/{len(self.results)} 项通过", flush=True)
        if failed:
            print("[FAILED] " + "、".join(failed), file=sys.stderr)
            return 1
        return 0


def http(
    base: str,
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    params: dict[str, object] | None = None,
) -> tuple[int, object]:
    """返回 (status, json|text)。4xx/5xx 不抛异常，交给调用方断言状态码。"""
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)  # noqa: S310 - 固定 http://localhost
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def login(base: str, username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(  # noqa: S310
        base + "/api/v1/admin/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))["access_token"]


async def seed() -> dict[str, int]:
    """两家公司招**同一个岗位**（多对多：1 条岗位 + 2 条关联）。"""
    from app.domain.services.job_persist_service import upsert_job_profile
    from app.infrastructure.database import async_session_factory

    title = f"{PREFIX}_Java工程师"
    async with async_session_factory() as session:
        profile, _ = await upsert_job_profile(
            session,
            {
                "title": title,
                "company": f"{PREFIX}_甲",
                "region": IMPORT_REGION,
                "city": IMPORT_CITY,
                "scale": "1000-9999人",
                "salary": "25-40K",
                "source_url": "https://example.com/job/acc5",
            },
        )
        await upsert_job_profile(
            session,
            {"title": title, "company": f"{PREFIX}_乙", "region": "北京市", "city": "北京市"},
        )
        await session.commit()

        from app.domain.models.company import Company
        from sqlalchemy import select

        ids: dict[str, int] = {"job": int(profile.id)}
        for alias, name in (("company_a", f"{PREFIX}_甲"), ("company_b", f"{PREFIX}_乙")):
            ids[alias] = int(
                (await session.execute(select(Company.id).where(Company.name == name))).scalar_one()
            )
        return ids


async def facts(ids: dict[str, int]) -> dict[str, object]:
    """直查库：写路径到底存了什么（**短名**还是全名）、关联有几条。"""
    from app.infrastructure.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        company = (
            await session.execute(
                text("SELECT region, city, scale FROM companies WHERE id = :i"),
                {"i": ids["company_a"]},
            )
        ).one()
        links = (
            await session.execute(
                text(
                    "SELECT count(*) FROM job_company_links WHERE job_profile_id = :i"
                ),
                {"i": ids["job"]},
            )
        ).scalar_one()
        return {"region": company[0], "city": company[1], "scale": company[2], "links": links}


async def cleanup() -> None:
    from app.infrastructure.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await session.commit()


async def run_checks(base: str, username: str, password: str, keep: bool) -> int:
    """**全程一个事件循环**。

    ⚠️ 踩过的坑：早先每段异步都单独 `asyncio.run(...)` → 每次都新建 loop，而
    `async_session_factory` 背后是**带连接池**的模块级 engine（连接绑在第一个 loop 上），
    第二个 `asyncio.run` 立刻抛
    `Future attached to a different loop` / `Event loop is closed`。
    pytest 里没暴露这个问题，是因为 `conftest` 的 `test_session_factory` 用的是 NullPool。
    所以：**seed / 查库 / 清理 全部放在同一个 loop 里**（HTTP 是同步 urllib，直接调用即可）。
    """
    c = Checker()
    try:
        token = login(base, username, password)
        c.check("管理员登录拿到 token", bool(token))

        ids = await seed()
        c.check("落库：1 条岗位 + 2 条在招关联", True, f"job={ids['job']}")

        stored = await facts(ids)
        c.check(
            "写路径把官方全名归一化成**短名**",
            (stored["region"], stored["city"]) == (EXPECT_REGION, EXPECT_CITY),
            f"库内 region/city = {stored['region']!r}/{stored['city']!r}"
            f"（下发 {IMPORT_REGION!r}/{IMPORT_CITY!r}）",
        )
        c.check("多对多：是 1 条岗位 + 2 条关联", stored["links"] == 2, f"links={stored['links']}")

        # ── ① 地域筛选（短名口径，coalesce(关联行, 公司)）──────────────────────
        job_id = ids["job"]
        status, data = http(
            base,
            "/api/v1/admin/jobs",
            token=token,
            params={"region": EXPECT_REGION, "city": EXPECT_CITY},
        )
        hit_ids = [i["id"] for i in data["items"]] if status == 200 else []
        c.check(
            f"岗位列表按「{EXPECT_REGION}/{EXPECT_CITY}」筛得到",
            status == 200 and job_id in hit_ids,
            f"status={status} total={data.get('total') if isinstance(data, dict) else data}",
        )

        status, data = http(base, "/api/v1/admin/jobs", token=token, params={"region": "北京"})
        c.check(
            "同一条岗位也能被第二家公司所在省筛到（多对多、地域各算各的）",
            status == 200 and job_id in [i["id"] for i in data["items"]],
            f"status={status}",
        )

        # ── ② 岗位详情：在招公司带招聘级字段 ──────────────────────────────────
        status, detail = http(base, f"/api/v1/admin/jobs/{job_id}", token=token)
        companies = detail.get("companies", []) if isinstance(detail, dict) else []
        first = companies[0] if companies else {}
        c.check(
            "岗位详情「在招公司」带 region/scale/salary/source_url",
            status == 200
            and len(companies) == 2
            and first.get("region") == EXPECT_REGION
            and first.get("scale") == "1000-9999人"
            and first.get("salary") == "25-40K"
            and first.get("source_url") == "https://example.com/job/acc5",
            f"companies={len(companies)} "
            f"first={ {k: first.get(k) for k in ('region', 'scale', 'salary', 'source_url')} }",
        )

        # ── ③ 公司筛选 + 级联选项 ────────────────────────────────────────────
        status, data = http(
            base, "/api/v1/admin/companies", token=token, params={"region": EXPECT_REGION}
        )
        c.check(
            "公司列表按省筛得到甲公司",
            status == 200 and ids["company_a"] in [i["id"] for i in data["items"]],
            f"status={status}",
        )

        for scope in ("companies", "jobs"):
            status, geo = http(base, f"/api/v1/admin/{scope}/geo-options", token=token)
            ok = (
                status == 200
                and len(geo["regions"]) >= 34  # 官方参考数据在位
                and EXPECT_REGION in geo["regions"]
                and EXPECT_CITY in geo["cities_by_region"].get(EXPECT_REGION, [])
            )
            c.check(f"/admin/{scope}/geo-options 含官方参考数据与库内地域", ok, f"status={status}")

        # ── ④ 删公司 204 回归（任务 5 的核心项）──────────────────────────────
        status, body = http(
            base, f"/api/v1/admin/companies/{ids['company_b']}", token=token, method="DELETE"
        )
        c.check(
            "删第二家公司 = **204**（P2 时代这里是 500）",
            status == 204,
            f"status={status} body={str(body)[:120]}",
        )

        status, detail = http(base, f"/api/v1/admin/jobs/{job_id}", token=token)
        remaining = detail.get("companies", []) if isinstance(detail, dict) else []
        c.check(
            "岗位本身不受影响，且只剩甲公司的关联",
            status == 200
            and [x["company_id"] for x in remaining] == [ids["company_a"]]
            and detail.get("company_count") == 1,
            f"status={status} companies={[x['company_id'] for x in remaining]}",
        )

        status, data = http(base, "/api/v1/admin/jobs", token=token, params={"region": "北京"})
        c.check(
            "删掉北京那家后，按「北京」筛不到了",
            status == 200 and job_id not in [i["id"] for i in data["items"]],
            f"status={status} total={data.get('total') if isinstance(data, dict) else data}",
        )

        # ── ⑤ 删岗位 204 回归（§18）──────────────────────────────────────────
        status, body = http(base, f"/api/v1/admin/jobs/{job_id}", token=token, method="DELETE")
        c.check("删岗位 = **204**（§18 修的就是这里必 500）", status == 204, f"status={status}")

        return c.summary()
    finally:
        # 清理也在同一个 loop 里；按**前缀**清，所以 seed 中途失败也能收拾干净
        if keep:
            print(f"\n[KEEP] 保留现场，前缀 {PREFIX}（记得手工清理）", flush=True)
        else:
            try:
                await cleanup()
                print(f"\n[CLEAN] 已按前缀 {PREFIX} 清理", flush=True)
            except Exception as exc:  # noqa: BLE001 - 清理失败不掩盖真正的失败项
                print(f"[WARN] 清理失败：{type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="任务 5 真栈验收（多对多 + 省市级联）")
    parser.add_argument("--base-url", default="http://localhost:8001", help="容器内后端地址")
    parser.add_argument("--username", default="s7admin")
    parser.add_argument("--password", default="***REMOVED-LEAKED-CREDENTIAL***")  # 开发库账号，见交接文档
    parser.add_argument("--keep", action="store_true", help="保留测试数据，便于排查")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_checks(args.base_url, args.username, args.password, args.keep))
    except Exception as exc:  # noqa: BLE001 - CLI 入口，给出可读信息
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
