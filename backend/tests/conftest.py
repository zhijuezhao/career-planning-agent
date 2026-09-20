import asyncio
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from app.config import get_settings
from app.infrastructure.database import async_session_factory, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
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
    # 注意：pytest 模块没有 SimpleNamespace，必须用标准库 types.SimpleNamespace
    # （原写法 `pytest.SimpleNamespace` 会让所有依赖 authed_user 的测试在 setup 阶段
    #  报 AttributeError，2026-09-18 修复）
    return SimpleNamespace(id=user["id"], username=user["username"])


@pytest_asyncio.fixture
async def db_session():
    """新开一个 async session（连 dev DB），供测试直接构造行。"""
    async with async_session_factory() as session:
        yield session


# ── Admin 测试共享 fixture（S1：消灭 event-loop ERROR）─────────────────────────
# 背景：原先 11 个 test_admin_*.py 各自用 asyncio.new_event_loop() + loop.close()
# 做"注册后提权为 admin"；其中 4 个文件用的是应用的【池化】引擎
# async_session_factory，asyncpg 连接会留在池里，临时 loop 关闭后被下一个 loop
# 复用 → Windows 下必现 "Event loop is closed"。
# 现统一为：conftest 的 test_session_factory（NullPool）+ asyncio.run()。


def _unique_username(prefix: str, module_name: str) -> str:
    """模块级唯一用户名（注意用户名上限 50 字符）。"""
    short = module_name.split(".")[-1].replace("test_admin_", "")
    return f"{prefix}_{short}_{int(time.time() * 1000)}"


def _register(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _set_role(username: str, role: str) -> None:
    async with test_session_factory() as session:
        await session.execute(
            text("UPDATE users SET role = :role WHERE username = :u"),
            {"role": role, "u": username},
        )
        await session.commit()


async def _fetch_user_id(username: str) -> int:
    async with test_session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": username}
        )
        return result.scalar_one()


@pytest.fixture(scope="module")
def admin_token(client, request) -> str:
    """模块级管理员 token：注册 -> 提权 admin -> 登录。"""
    uname = _unique_username("admin", request.module.__name__)
    _register(client, uname, "admin123456")
    asyncio.run(_set_role(uname, "admin"))
    return _login(client, uname, "admin123456")


@pytest.fixture(scope="module")
def student_token(client, request) -> str:
    """模块级普通学生 token（用于 403 越权用例）。"""
    uname = _unique_username("student", request.module.__name__)
    _register(client, uname, "student123456")
    return _login(client, uname, "student123456")


@pytest.fixture(scope="module")
def other_user_id(client, request) -> int:
    """再注册一个普通用户并返回其 id（test_admin_auth 越权用例使用）。"""
    uname = _unique_username("other", request.module.__name__)
    _register(client, uname, "other123456")
    return asyncio.run(_fetch_user_id(uname))
