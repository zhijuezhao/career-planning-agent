import time

import pytest
from app.config import get_settings
from app.infrastructure.database import async_session_factory, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

settings = get_settings()

test_engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,
)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def authed_user(client):
    """注册+登录一个唯一用户，设置 Bearer 头，返回 user 对象（含 id）。"""
    uname = f"journey_{int(time.time() * 1000)}"
    reg = client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "journey123",
    })
    assert reg.status_code == 201, reg.text
    user = reg.json()
    assert "id" in user

    login = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "journey123",
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {token}"
    return pytest.SimpleNamespace(id=user["id"], username=user["username"])


@pytest.fixture
async def db_session():
    """新开一个 async session（连 dev DB），供测试直接构造行。"""
    async with async_session_factory() as session:
        yield session
