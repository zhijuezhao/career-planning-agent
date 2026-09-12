import asyncio
import io
import time

import pytest
from app.config import get_settings
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

_settings = get_settings()
_test_engine = create_async_engine(_settings.database_url, poolclass=NullPool)

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_token(client: TestClient) -> str:
    uname = f"admin_import_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "admin123456",
    })
    from app.domain.models.user import User

    async def set_admin():
        async with AsyncSession(_test_engine) as session:
            result = await session.execute(select(User).where(User.username == uname))
            user = result.scalar_one_or_none()
            if user:
                user.role = "admin"
                await session.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(set_admin())
    loop.close()

    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "admin123456",
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def student_token(client: TestClient) -> str:
    uname = f"student_import_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "student123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "student123456",
    })
    return resp.json()["access_token"]


class TestImportAPI:
    def test_list_import_jobs(self, admin_token: str, client: TestClient):
        """Test listing import jobs."""
        resp = client.get(
            "/api/v1/admin/import",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_upload_file(self, admin_token: str, client: TestClient):
        """Test uploading a file."""
        file_content = b"title,company,city\nTest Job,Test Company,Beijing\n"
        resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("test.csv", io.BytesIO(file_content), "text/csv")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["file_name"] == "test.csv"
        assert data["status"] == "pending"

    def test_upload_invalid_extension(self, admin_token: str, client: TestClient):
        """Test uploading a file with invalid extension."""
        resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_get_import_job_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent import job."""
        resp = client.get(
            "/api/v1/admin/import/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_get_progress_not_found(self, admin_token: str, client: TestClient):
        """Test getting progress of non-existent job."""
        resp = client.get(
            "/api/v1/admin/import/999999/progress",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_process_and_check_progress(self, admin_token: str, client: TestClient):
        """Test processing an import job and checking progress."""
        file_content = b"title,company\nJob,Company\n"
        upload_resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("process_test.csv", io.BytesIO(file_content), "text/csv")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = upload_resp.json()["id"]

        process_resp = client.post(
            f"/api/v1/admin/import/{job_id}/process",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert process_resp.status_code == 200
        assert process_resp.json()["status"] == "processing"

        progress_resp = client.get(
            f"/api/v1/admin/import/{job_id}/progress",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert progress_resp.status_code == 200
        data = progress_resp.json()
        assert data["job_id"] == job_id
        assert "progress_pct" in data


class TestImportAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access import endpoints."""
        resp = client.get(
            "/api/v1/admin/import",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
