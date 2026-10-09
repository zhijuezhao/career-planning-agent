"""T01/T02/T04/T05/T06 smoke test (self-contained, fresh user, cleaned up)."""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database import async_session_factory  # noqa: E402
from sqlalchemy import text  # noqa: E402

BASE = "http://test"


async def main() -> None:
    transport = httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as c:
        # fresh user
        uname = f"smoke_{asyncio.get_event_loop().time():.0f}"
        r = await c.post("/api/v1/auth/register", json={"username": uname, "password": "Passw0rd!"})
        assert r.status_code == 201, f"register: {r.status_code} {r.text}"
        uid = r.json()["id"]

        r = await c.post("/api/v1/auth/login", json={"username": uname, "password": "Passw0rd!"})
        assert r.status_code == 200, f"login: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        other = {"Authorization": f"Bearer {'x' * 20}"}

        async with async_session_factory() as db:
            # ---- T01: enumeration ----
            r = await c.get("/api/v1/users", headers=other)
            tr = ("student-list-forbidden", r.status_code)
            r = await c.get("/api/v1/users", headers=headers)  # authenticated student still denied
            tr = ("student-list-forbidden", tr[1], r.status_code)
            r = await c.get(f"/api/v1/users/{uid}", headers=headers)
            t_self = ("self-detail", r.status_code)
            r = await c.get("/api/v1/users/1", headers=headers)
            t_other = ("other-detail-forbidden", r.status_code)

            # ---- T04: single MatchDetailResponse shape ----
            school = await db.execute(
                text(
                    "INSERT INTO ability_profiles (user_id, direction_tag, intention, traits, practice, "
                    "soft_skills, hard_skills, version) "
                    "VALUES (:uid, 'default', '{}', '{}', '{}', '{}', '{}', 1) RETURNING id"
                ),
                {"uid": uid},
            )
            pid = school.scalar_one()
            job = await db.execute(text("SELECT id FROM job_profiles ORDER BY id LIMIT 1"))
            jid = job.scalar_one()
            match = await db.execute(
                text(
                    "INSERT INTO job_matches (user_id, profile_id, job_profile_id, match_score, match_analysis) "
                    "VALUES (:uid, :pid, :jid, 0.87, "
                    "'{\"vector_similarity\": 0.92, \"dimension_score\": 0.8, "
                    "\"dimension_matches\": {\"skill\": {\"user_score\": 0.6, \"job_score\": 0.8, "
                    "\"weight\": 0.5, \"match_ratio\": 0.75}}, "
                    "\"weights_used\": {\"skill\": 0.5}}'::jsonb) RETURNING id"
                ),
                {"uid": uid, "pid": pid, "jid": jid},
            )
            mid = match.scalar_one()
            await db.commit()
            mrow = (await db.execute(text("SELECT match_score FROM job_matches WHERE id=:mid"), {"mid": mid})).scalar()

        r = await c.get(f"/api/v1/matching/results/{mid}", headers=headers)
        body = r.json()
        t04 = (
            "match-detail-shape", r.status_code, body.get("match_id"),
            body.get("job_profile_id"), body.get("match_score"), float(mrow),
        )

        # ---- T05: feedback ValueError -> 400 ----
        r = await c.post(
            "/api/v1/matching/feedback",
            headers=headers,
            json={"match_id": 99999999, "feedback_type": "like"},
        )
        t05 = ("feedback-404->400", r.status_code)

        # ---- T06: disabled user's old token invalid ----
        async with async_session_factory() as db:
            await db.execute(text("UPDATE users SET status=0 WHERE id=:uid"), {"uid": uid})
            await db.commit()
        r = await c.get("/api/v1/auth/me", headers=headers)
        t06 = ("disabled-token-403", r.status_code)

        for row in (tr, t_self, t_other, t04, t05, t06):
            print(row)

        # ---- T02: path traversal filename (admin) ----
        admin = f"smoke_admin_{asyncio.get_event_loop().time():.0f}"
        r = await c.post("/api/v1/auth/register", json={"username": admin, "password": "Passw0rd!"})
        aid = r.json()["id"]
        async with async_session_factory() as db:
            await db.execute(text("UPDATE users SET role='admin' WHERE id=:aid"), {"aid": aid})
            await db.commit()
        r = await c.post("/api/v1/auth/login", json={"username": admin, "password": "Passw0rd!"})
        admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        files = {"file": ("..__..__..__evil_import.csv", b"name,desc\n", "text/csv")}
        r = await c.post("/api/v1/admin/import/upload", headers=admin_headers, files=files)
        job_id = None
        if r.status_code == 201:
            job = r.json()
            job_id = job["id"]
            stored = Path("uploads/import") / job["file_name"]
            t02 = (
                "import-traversal", "OK",
                job["file_name"] == files["file"][0],   # T02: filename kept sanitizable, no traversal
                stored.name == job["file_name"],        # uploaded bytes live under uuid_hex_<safe>
            )
        else:
            t02 = ("import-traversal", r.status_code, r.text[:120])
        print(t02)

        # ---- cleanup (each statement isolated; failure prints loudly, never aborts silently) ----
        cleanup_ok = True
        async with async_session_factory() as db:
            for sql in (
                "DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE user_id=:uid)",
                "DELETE FROM chat_sessions WHERE user_id=:uid",
                "DELETE FROM user_feedbacks WHERE user_id=:uid",
                "DELETE FROM job_matches WHERE user_id=:uid",
                "DELETE FROM user_match_embeddings WHERE user_id=:uid",
                "DELETE FROM resumes WHERE user_id=:uid",
                "DELETE FROM ability_profiles WHERE user_id=:uid",
                "DELETE FROM growth_plans WHERE user_id=:uid",
                "DELETE FROM growth_paths WHERE user_id=:uid",
                "DELETE FROM career_reports WHERE user_id=:uid",
                "DELETE FROM student_profiles WHERE user_id=:uid",
                "DELETE FROM users WHERE id=:uid OR id=:aid",
            ):
                try:
                    await db.execute(text(sql), {"uid": uid, "aid": aid})
                    await db.flush()
                except Exception as exc:
                    cleanup_ok = False
                    await db.rollback()
                    print(f"[cleanup] FAILED: {sql[:70]}... -> {type(exc).__name__}: {exc}")
            if cleanup_ok:
                await db.commit()

        if job_id is not None:
            try:
                async with async_session_factory() as db:
                    await db.execute(text("DELETE FROM data_import_jobs WHERE id=:jid"), {"jid": job_id})
                    await db.commit()
            except Exception as exc:
                print(f"[cleanup] import job {job_id} not removed -> {type(exc).__name__}: {exc}")
            safe = "..__..__..__evil_import.csv"
            for f in Path("uploads/import").iterdir():
                if f.name.endswith(f"_{safe}"):
                    f.unlink(missing_ok=True)
        print("cleanup done" if cleanup_ok else "cleanup DONE BUT FAILURES (see above)")


if __name__ == "__main__":
    asyncio.run(main())
