import asyncio
import uuid

from app.domain.models import ProfileSnapshot, ReportRecord, StudentProfile
from tests.conftest import test_session_factory


# ─── helper ────────────────────────────────────────────────────────────────
async def make_snapshot(db, user_id, *, form_complete=False,
                        five_layers=None, dims=None, embedding=None):
    """构造一条 ProfileSnapshot（async，真实 await 提交）。

    R-2.2 修正（相对 brief）：
    - profile_id 使用注册用户真实 id（FK: profile_snapshots.profile_id
      → student_profiles.user_id），不再用魔数 1；
    - 先建 StudentProfile(user_id) 行（非空 FK 依赖）；
    - 传 embedding=[0.0]*1024（Vector(1024) 非空且无 server default）。
    """
    profile = await db.get(StudentProfile, user_id)
    if profile is None:
        db.add(StudentProfile(user_id=user_id))
        await db.flush()
    snap = ProfileSnapshot(
        user_id=user_id,
        profile_id=user_id,
        form_raw_json={"basic": True, "intention": {"v": 1}} if form_complete else {},
        five_layers_json=five_layers or {},
        six_dim_scores_json=dims or {},
        embedding=embedding if embedding is not None else [0.0] * 1024,
        serial_no=uuid.uuid4(),
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


def _seed(user_id: int, *, form_complete: bool = False, with_report: bool = False):
    """在**自己的 loop + 自己的 session** 里造数据，返回 (snapshot_id, report_id)。

    为什么不用 `db_session` fixture + `@pytest.mark.asyncio`（2026-10-09 CI 修复）：
    本文件的用例既要 `client`（TestClient 的 portal loop）又要直接写库。
    若用 pytest-asyncio 的 async fixture 写库，就会**同时存在两个事件循环** ——
    写库 session 的 close 落在另一个 loop 上，teardown 报
    `got Future ... attached to a different loop`（Linux CI 必现；Windows 表现为
    "Event loop is closed"）。这里改成同步用例 + `asyncio.run`（仓库其它测试同款写法），
    数据准备与 HTTP 请求各自独立，不再跨 loop 复用连接。
    """
    async def _inner():
        async with test_session_factory() as session:
            snap = await make_snapshot(session, user_id, form_complete=form_complete)
            report_id = None
            if with_report:
                record = ReportRecord(
                    user_id=user_id,
                    profile_snapshot_id=snap.id,
                    serial_no=uuid.uuid4(),
                    report_text="...",
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
                report_id = record.id
            return snap.id, report_id

    return asyncio.run(_inner())


# ─── 测试用例（三段 zone 判定）───────────────────────────────────────────────
def test_zero_snapshot_returns_welcome(client, authed_user):
    res = client.get("/api/v1/journey/status")
    assert res.json()["zone"] == "welcome"
    assert res.json()["guide_step"] is None


def test_snapshot_no_report_returns_guide(client, authed_user):
    snap_id, _ = _seed(authed_user.id)
    res = client.get("/api/v1/journey/status")
    data = res.json()
    assert data["zone"] == "guide"
    assert data["guide_step"] in ("resume", "parse", "match", "career")
    assert data["snapshot_id"] == snap_id


def test_report_exists_returns_business(client, authed_user):
    _, report_id = _seed(authed_user.id, form_complete=True, with_report=True)
    res = client.get("/api/v1/journey/status")
    assert res.json()["zone"] == "business"
    assert res.json()["report_id"] == report_id
