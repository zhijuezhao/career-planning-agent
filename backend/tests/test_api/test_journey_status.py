import uuid

import pytest
from app.domain.models import ProfileSnapshot, ReportRecord, StudentProfile


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


# ─── 测试用例（三段 zone 判定）───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_zero_snapshot_returns_welcome(client, authed_user):
    res = client.get("/api/v1/journey/status")
    assert res.json()["zone"] == "welcome"
    assert res.json()["guide_step"] is None


@pytest.mark.asyncio
async def test_snapshot_no_report_returns_guide(client, authed_user, db_session):
    await make_snapshot(db_session, authed_user.id)
    res = client.get("/api/v1/journey/status")
    data = res.json()
    assert data["zone"] == "guide"
    assert data["guide_step"] in ("resume", "parse", "match", "career")
    assert data["snapshot_id"] is not None


@pytest.mark.asyncio
async def test_report_exists_returns_business(client, authed_user, db_session):
    snap = await make_snapshot(db_session, authed_user.id, form_complete=True)
    db_session.add(ReportRecord(user_id=authed_user.id, profile_snapshot_id=snap.id,
                                serial_no=uuid.uuid4(), report_text="..."))
    await db_session.commit()
    res = client.get("/api/v1/journey/status")
    assert res.json()["zone"] == "business"
    assert res.json()["report_id"] is not None
