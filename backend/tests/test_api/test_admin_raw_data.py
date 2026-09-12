import asyncio
import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_token(client: TestClient) -> str:
    uname = f"admin_raw_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "admin123456",
    })
    from app.infrastructure.database import async_session_factory
    from app.domain.models.user import User

    async def set_admin():
        async with async_session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(User).where(User.username == uname)
            )
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


class TestRawDataListAPI:
    def test_list_raw_data(self, admin_token: str, client: TestClient):
        """Test listing raw data."""
        resp = client.get(
            "/api/v1/admin/raw-data",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_get_raw_data_not_found(self, admin_token: str, client: TestClient):
        """Test getting non-existent raw data."""
        resp = client.get(
            "/api/v1/admin/raw-data/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_filter_raw_data(self, admin_token: str, client: TestClient):
        """Test filtering raw data."""
        resp = client.get(
            "/api/v1/admin/raw-data?industry=互联网",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    def test_batch_delete_empty_ids(self, admin_token: str, client: TestClient):
        """Test batch delete with empty IDs."""
        resp = client.post(
            "/api/v1/admin/raw-data/batch-delete",
            json=[],
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400
