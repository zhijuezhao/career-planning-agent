"""B2-4 回归用例：用户字段（qq/wechat）、角色白名单、用户管理改造（改状态/编辑/删除）。

约定（见 `docs/HANDOFF-2026-09-25-admin-batch2.md`）：
- 本文件注册的用户一律 `b24_<ts>_*` 前缀，模块结束精确清理，不留脏行；
- 「删除用户可用」必须覆盖 **NO ACTION 外键链**（`chat_sessions` / `chat_messages` / `resumes`）
  —— 那正是 B2-4 修掉的真 bug（实测 1520 个用户里 11 个删不掉，接口直接 500）。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from app.config import get_settings
from app.main import app
from app.utils.file_storage import save_upload_file
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

_settings = get_settings()
_engine = create_async_engine(_settings.database_url, poolclass=NullPool)

_ts = str(int(time.time()))
_PREFIX = f"b24_{_ts}"

#: 本模块注册（并负责清理）的用户名
_created: list[str] = []


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _scalar(sql: str, **params: object) -> object:
    async with AsyncSession(_engine) as session:
        return (await session.execute(text(sql), params)).scalar()


def _register(client: TestClient, suffix: str) -> int:
    """注册一个 b24 用户并返回 id。"""
    uname = f"{_PREFIX}_{suffix}"
    resp = client.post("/api/v1/auth/register", json={"username": uname, "password": "b24pass123"})
    assert resp.status_code == 201, resp.text
    _created.append(uname)
    return int(asyncio.run(_scalar("SELECT id FROM users WHERE username = :u", u=uname)))


async def _seed_dependents(uid: int) -> None:
    """给用户造齐五类关联行：覆盖 CASCADE 链（画像/快照/报告）与 NO ACTION 链（会话/简历）。"""
    async with AsyncSession(_engine) as session:
        await session.execute(
            text("INSERT INTO student_profiles (user_id, resume_form) VALUES (:i, '{}'::jsonb)"),
            {"i": uid},
        )
        snapshot_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO profile_snapshots
                        (user_id, profile_id, form_raw_json, five_layers_json,
                         six_dim_scores_json, embedding, description, serial_no)
                    VALUES
                        (:i, :i, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                         (SELECT array_fill(0.0, ARRAY[1024])::vector), :d, gen_random_uuid())
                    RETURNING id
                    """
                ),
                {"i": uid, "d": "b24 snapshot"},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO report_records"
                " (user_id, profile_snapshot_id, description, report_text, serial_no)"
                " VALUES (:i, :s, :d, 'b24 report', gen_random_uuid())"
            ),
            {"i": uid, "s": snapshot_id, "d": "b24 report"},
        )
        session_id = (
            await session.execute(
                text("INSERT INTO chat_sessions (user_id, title) VALUES (:i, :t) RETURNING id"),
                {"i": uid, "t": "b24 session"},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO chat_messages (session_id, role, content, tokens_used)"
                " VALUES (:s, 'user', 'b24 hi', 0)"
            ),
            {"s": session_id},
        )
        await session.execute(
            text(
                "INSERT INTO resumes"
                " (user_id, file_name, file_path, file_size, content_hash, version)"
                " VALUES (:i, 'b24_cv.pdf', '/tmp/b24_cv.pdf', 1234, :h, 1)"
            ),
            {"i": uid, "h": f"b24hash{uid}"},
        )
        await session.commit()


async def _dependent_counts(uid: int) -> dict[str, int]:
    async with AsyncSession(_engine) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM resumes          WHERE user_id = :i) AS resumes,
                      (SELECT count(*) FROM chat_sessions    WHERE user_id = :i) AS sessions,
                      (SELECT count(*) FROM student_profiles WHERE user_id = :i) AS profiles,
                      (SELECT count(*) FROM profile_snapshots WHERE user_id = :i) AS snapshots,
                      (SELECT count(*) FROM report_records   WHERE user_id = :i) AS reports
                    """
                ),
                {"i": uid},
            )
        ).one()
        return {k: int(v) for k, v in row._mapping.items()}


def _resolve_stored(raw: str) -> Path:
    """把库里的 file_path（相对 backend 工作目录）解析成宿主绝对路径。"""
    path = Path(raw)
    return path if path.is_absolute() else Path.cwd() / path


async def _insert_resume(uid: int, file_path: str, content_hash: str) -> None:
    """插一行简历记录（磁盘文件由 `save_upload_file` 按生产约定真实写盘）。"""
    async with AsyncSession(_engine) as session:
        await session.execute(
            text(
                "INSERT INTO resumes"
                " (user_id, file_name, file_path, file_size, content_hash, version)"
                " VALUES (:i, 'b24_cv.pdf', :p, 12, :h, 1)"
            ),
            {"i": uid, "p": file_path, "h": content_hash},
        )
        await session.commit()


async def _purge(usernames: list[str]) -> None:
    """按外键顺序清掉这些用户及其关联行（含本模块的 conftest 管理员账号）。"""
    async with AsyncSession(_engine) as session:
        for uname in usernames:
            uid = (
                await session.execute(text("SELECT id FROM users WHERE username = :u"), {"u": uname})
            ).scalar()
            if uid is None:
                continue
            await session.execute(
                text(
                    "DELETE FROM chat_messages WHERE session_id IN"
                    " (SELECT id FROM chat_sessions WHERE user_id = :i)"
                ),
                {"i": uid},
            )
            await session.execute(text("DELETE FROM chat_sessions WHERE user_id = :i"), {"i": uid})
            await session.execute(text("DELETE FROM resumes WHERE user_id = :i"), {"i": uid})
            await session.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        await session.commit()


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_credentials):
    """跑完把本模块造的用户（含 conftest 生成的模块管理员）精确删掉。"""
    yield
    asyncio.run(_purge([admin_credentials[0], *_created]))


class TestUserFields:
    """B2-4：users.qq / users.wechat 可读可写（列在 B2-0 已建好，本次接 ORM 与接口）。"""

    def test_qq_wechat_roundtrip(self, admin_token: str, client: TestClient):
        uid = _register(client, "fields")

        resp = client.put(
            f"/api/v1/admin/users/{uid}",
            json={"qq": "123456789", "wechat": "wx_b24_user"},
            headers=_h(admin_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["qq"] == "123456789"
        assert body["wechat"] == "wx_b24_user"

        # 落到库里才算数（不只是回显）
        assert asyncio.run(_scalar("SELECT qq FROM users WHERE id = :i", i=uid)) == "123456789"
        assert asyncio.run(_scalar("SELECT wechat FROM users WHERE id = :i", i=uid)) == "wx_b24_user"

        # 单查接口也要回显
        single = client.get(f"/api/v1/admin/users/{uid}", headers=_h(admin_token)).json()
        assert single["qq"] == "123456789"
        assert single["wechat"] == "wx_b24_user"

    def test_blank_clears_fields(self, admin_token: str, client: TestClient):
        """清空输入框 = 真清空（NULL），不是往库里写空字符串。"""
        uid = _register(client, "blank")
        client.put(
            f"/api/v1/admin/users/{uid}",
            json={"qq": "987654321", "wechat": "wx_tmp", "phone": "13700000000"},
            headers=_h(admin_token),
        )

        resp = client.put(
            f"/api/v1/admin/users/{uid}",
            json={"qq": "", "wechat": "   ", "phone": ""},
            headers=_h(admin_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["qq"] is None
        assert body["wechat"] is None
        assert body["phone"] is None
        assert asyncio.run(_scalar("SELECT qq FROM users WHERE id = :i", i=uid)) is None

    def test_invalid_qq_rejected(self, admin_token: str, client: TestClient):
        uid = _register(client, "badqq")
        resp = client.put(
            f"/api/v1/admin/users/{uid}", json={"qq": "abc123"}, headers=_h(admin_token)
        )
        assert resp.status_code == 422
        assert asyncio.run(_scalar("SELECT qq FROM users WHERE id = :i", i=uid)) is None

    def test_keyword_matches_qq_and_wechat(self, admin_token: str, client: TestClient):
        """B2-4 的字段必须搜得到，否则建了列也只能一页页翻。"""
        uid = _register(client, "kw")
        client.put(
            f"/api/v1/admin/users/{uid}",
            json={"qq": "556677889", "wechat": "wx_kw_b24"},
            headers=_h(admin_token),
        )

        for keyword in ("556677889", "wx_kw_b24"):
            items = client.get(
                "/api/v1/admin/users", params={"keyword": keyword}, headers=_h(admin_token)
            ).json()["items"]
            assert any(item["id"] == uid for item in items), f"keyword={keyword} 未命中"


class TestRoleWhitelist:
    """B2-4：角色白名单（唯一来源 `app/core/roles.py`）。"""

    def test_update_rejects_role_outside_whitelist(self, admin_token: str, client: TestClient):
        uid = _register(client, "rolebad")

        bad = client.put(
            f"/api/v1/admin/users/{uid}", json={"role": "superuser"}, headers=_h(admin_token)
        )
        assert bad.status_code == 422
        # 库里角色没被改脏
        assert asyncio.run(_scalar("SELECT role FROM users WHERE id = :i", i=uid)) == "student"

        ok = client.put(
            f"/api/v1/admin/users/{uid}", json={"role": "admin"}, headers=_h(admin_token)
        )
        assert ok.status_code == 200 and ok.json()["role"] == "admin"

        # 复原，避免影响其它用例对角色分布的假设
        back = client.put(
            f"/api/v1/admin/users/{uid}", json={"role": "student"}, headers=_h(admin_token)
        )
        assert back.status_code == 200 and back.json()["role"] == "student"

    def test_filter_rejects_role_outside_whitelist(self, admin_token: str, client: TestClient):
        bad = client.get(
            "/api/v1/admin/users", params={"role": "superuser"}, headers=_h(admin_token)
        )
        assert bad.status_code == 422

        ok = client.get("/api/v1/admin/users", params={"role": "admin"}, headers=_h(admin_token))
        assert ok.status_code == 200
        assert all(item["role"] == "admin" for item in ok.json()["items"])


class TestUserManagement:
    """B2-4：改状态 / 编辑 / 删除真正可用（并防止管理员把自己锁在门外）。"""

    def test_delete_user_with_dependents(self, admin_token: str, client: TestClient):
        """有简历/对话/画像/快照/报告的用户必须能删掉（修复前是 500 FK violation）。"""
        uid = _register(client, "deps")
        asyncio.run(_seed_dependents(uid))
        before = asyncio.run(_dependent_counts(uid))
        assert before == {
            "resumes": 1,
            "sessions": 1,
            "profiles": 1,
            "snapshots": 1,
            "reports": 1,
        }

        resp = client.delete(f"/api/v1/admin/users/{uid}", headers=_h(admin_token))
        assert resp.status_code == 204, resp.text

        # 五类子行全部消失（会话能删掉即证明 chat_messages 先被删了：否则 FK 会拦住）
        assert asyncio.run(_dependent_counts(uid)) == {k: 0 for k in before}
        assert client.get(f"/api/v1/admin/users/{uid}", headers=_h(admin_token)).status_code == 404

    def test_delete_self_rejected(self, admin_token: str, admin_credentials, client: TestClient):
        admin_id = asyncio.run(
            _scalar("SELECT id FROM users WHERE username = :u", u=admin_credentials[0])
        )
        resp = client.delete(f"/api/v1/admin/users/{admin_id}", headers=_h(admin_token))
        assert resp.status_code == 400
        # 账号还在，token 还能用
        assert client.get(f"/api/v1/admin/users/{admin_id}", headers=_h(admin_token)).status_code == 200

    def test_self_disable_and_demote_rejected(
        self, admin_token: str, admin_credentials, client: TestClient
    ):
        """自锁保护：禁用自己 / 取消自己的管理员身份都拒绝，但其它字段仍可改。"""
        admin_id = asyncio.run(
            _scalar("SELECT id FROM users WHERE username = :u", u=admin_credentials[0])
        )

        disable = client.put(
            f"/api/v1/admin/users/{admin_id}", json={"status": 0}, headers=_h(admin_token)
        )
        assert disable.status_code == 400

        demote = client.put(
            f"/api/v1/admin/users/{admin_id}", json={"role": "student"}, headers=_h(admin_token)
        )
        assert demote.status_code == 400

        # 守卫只拦自锁两项，普通字段照改
        ok = client.put(
            f"/api/v1/admin/users/{admin_id}", json={"qq": "10001"}, headers=_h(admin_token)
        )
        assert ok.status_code == 200 and ok.json()["qq"] == "10001"
        assert asyncio.run(_scalar("SELECT status FROM users WHERE id = :i", i=admin_id)) == 1
        assert asyncio.run(_scalar("SELECT role FROM users WHERE id = :i", i=admin_id)) == "admin"

    def test_status_toggle_still_works(self, admin_token: str, client: TestClient):
        """改状态（管理端开关走的就是这个接口）对**别人**正常生效。"""
        uid = _register(client, "toggle")

        off = client.put(
            f"/api/v1/admin/users/{uid}", json={"status": 0}, headers=_h(admin_token)
        )
        assert off.status_code == 200 and off.json()["status"] == 0
        # 被禁用的账号不能再登录
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": f"{_PREFIX}_toggle", "password": "b24pass123"},
            ).status_code
            == 403
        )

        on = client.put(f"/api/v1/admin/users/{uid}", json={"status": 1}, headers=_h(admin_token))
        assert on.status_code == 200 and on.json()["status"] == 1

    def test_stats_exposes_delete_scope(self, admin_token: str, client: TestClient):
        """删除确认框需要的关联计数（B2-4 新增 snapshot_count / profile_count）。"""
        uid = _register(client, "stats")
        asyncio.run(_seed_dependents(uid))

        data = client.get(f"/api/v1/admin/users/{uid}/stats", headers=_h(admin_token)).json()
        assert data["resume_count"] == 1
        assert data["report_count"] == 1
        assert data["chat_session_count"] == 1
        assert data["snapshot_count"] == 1
        assert data["profile_count"] == 1


class TestResumeFileCleanup:
    """附件①（2026-09-25 决定）：删用户时一并删该用户的简历磁盘文件。

    背景：简历写盘位置是 `{settings.upload_dir}/user_<id>/`（`save_upload_file`），
    而 `settings.upload_dir` 是相对 cwd 的 `./uploads` → 容器里即 `/app/backend/uploads`，
    也就是宿主 `backend/uploads/`。此前删用户只删库行，文件永久留下：
    实测该目录 106 个 PDF vs 库里 12 行，约 88% 是这么攒的。
    """

    def test_delete_user_removes_resume_files(self, admin_token: str, client: TestClient):
        uid = _register(client, "files")
        # 用生产同一个 helper 写盘，保证目录/命名约定与真实上传一致
        stored_path, digest = save_upload_file(b"%PDF-1.4 b24 test pdf", uid, "b24_cv.pdf")
        asyncio.run(_insert_resume(uid, stored_path, digest))
        target = _resolve_stored(stored_path)
        assert target.exists(), f"前置条件失败：{target} 不存在"

        resp = client.delete(f"/api/v1/admin/users/{uid}", headers=_h(admin_token))
        assert resp.status_code == 204, resp.text

        assert not target.exists(), f"简历文件未被删除：{target}"
        # 目录空了应一并清掉，否则磁盘上会攒一堆空 user_* 目录
        assert not target.parent.exists(), f"空目录未清理：{target.parent}"

    def test_path_guard_skips_files_outside_user_dir(self, admin_token: str, client: TestClient):
        """`file_path` 指向别人目录/目录外时**不许删**（前缀校验，防越权删除）。"""
        uid = _register(client, "guard")
        victim = Path.cwd() / "uploads" / "b24_guard_victim.pdf"
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_bytes(b"%PDF-1.4 victim")
        asyncio.run(_insert_resume(uid, "uploads/b24_guard_victim.pdf", "b24guardhash"))

        try:
            resp = client.delete(f"/api/v1/admin/users/{uid}", headers=_h(admin_token))
            assert resp.status_code == 204, resp.text
            assert victim.exists(), "目录外的文件被误删了（前缀校验失效）"
        finally:
            victim.unlink(missing_ok=True)
