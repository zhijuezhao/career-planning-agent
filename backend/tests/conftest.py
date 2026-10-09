import asyncio
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from app.config import get_settings
from app.infrastructure.database import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
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
    """新开一个 async session（连 dev DB），供测试直接构造行。

    ⚠️ 必须用 conftest 的 `test_session_factory`（**NullPool**），不能用应用的池化
    `async_session_factory` —— 后者会把 asyncpg 连接留在连接池里，而 pytest-asyncio 每个
    用例一个事件循环，连接在下一个 loop 里复用时 Windows 上**必现**
    `RuntimeError: Event loop is closed`（实测：`test_journey_status.py` 稳定报
    teardown ERROR）。这正是本文件 §"Admin 测试共享 fixture" 记的那个坑，只是
    `db_session` 当时漏改了。
    """
    async with test_session_factory() as session:
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
def admin_credentials(client, request) -> tuple[str, str]:
    """模块级管理员账号 (用户名, 密码)：注册 -> 提权 admin。

    S2 起单独提供：管理员登录用例需要明文凭据，而不只是 token。
    """
    uname = _unique_username("admin", request.module.__name__)
    password = "admin123456"
    _register(client, uname, password)
    asyncio.run(_set_role(uname, "admin"))
    return uname, password


@pytest.fixture(scope="module")
def admin_token(client, admin_credentials) -> str:
    """模块级管理员 token：注册 -> 提权 admin -> 登录。"""
    uname, password = admin_credentials
    return _login(client, uname, password)


@pytest.fixture(scope="module")
def student_credentials(client, request) -> tuple[str, str]:
    """模块级普通学生账号 (用户名, 密码)：S2 起供「学生登录 admin 被拒」用例复用。"""
    uname = _unique_username("student", request.module.__name__)
    password = "student123456"
    _register(client, uname, password)
    return uname, password


@pytest.fixture(scope="module")
def student_token(client, student_credentials) -> str:
    """模块级普通学生 token（用于 403 越权用例）。"""
    uname, password = student_credentials
    return _login(client, uname, password)


@pytest.fixture(scope="module")
def other_user_id(client, request) -> int:
    """再注册一个普通用户并返回其 id（test_admin_auth 越权用例使用）。"""
    uname = _unique_username("other", request.module.__name__)
    _register(client, uname, "other123456")
    return asyncio.run(_fetch_user_id(uname))


# ── 「保证库非空」的共享实现 ────────────────────────────────────────────────────
# 背景（2026-09-27 清库后暴露）：有一批用例**写的时候就假定 `job_profiles` 非空**
# （作者注释原话"真库现在有 82 条，替不掉"）—— 例如问「有哪些岗位」命中 L1 工作流、
# 断言有 viz；或"viz 行数/分布之和 == 岗位总数"这类对账断言。空库时工作流**故意不发图**
# （不编数据），于是它们全红。
# 更隐蔽的是：**全量跑时它们靠 `test_admin_jobs` 泄漏的岗位"碰巧"通过**（顺序相关），
# 单独跑或清库后就红 —— 所以统一用下面的实现让它们与库状态、用例顺序无关。
# 库里本来有数据就不插手，用完只删自己造的那两条。

_ENSURE_JOBS_PREFIX = f"ensjobs_{int(time.time())}"


async def seed_jobs_if_empty() -> bool:
    """`job_profiles` 为空时造 2 条岗位；返回**是否本次造的**（有数据则 False）。"""
    from app.domain.models.job import JobProfile
    from app.domain.services.job_persist_service import upsert_job_profile

    async with test_session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(JobProfile))
        ).scalar() or 0
        if total:
            return False
        for suffix in ("甲", "乙"):
            await upsert_job_profile(session, {"title": f"{_ENSURE_JOBS_PREFIX}_{suffix}"})
        await session.commit()
        return True


async def drop_seeded_jobs() -> None:
    """删掉 `seed_jobs_if_empty()` 造的那两条（只按自己的前缀删，不碰其他数据）。"""
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"),
            {"p": f"{_ENSURE_JOBS_PREFIX}%"},
        )
        await session.commit()


@pytest.fixture
def ensure_some_jobs():
    """函数级：保证库非空（用完还原）。

    需要**类级/模块级**时，别复制这套逻辑 —— 直接在你的 fixture 里调
    `seed_jobs_if_empty()` / `drop_seeded_jobs()`（同一个实现，作用域各取所需）。
    """
    created = asyncio.run(seed_jobs_if_empty())
    yield
    if created:
        asyncio.run(drop_seeded_jobs())


# ── 「保证库里有岗位向量」的共享实现 ────────────────────────────────────────────
# 背景（2026-10-09 CI 修复）：`test_e2e_business_chain` 的匹配/报告用例前提是
# **库里有岗位向量**（"库里有 ≥3 条岗位向量就必然拿到 ≥3 条候选"）。开发库里有
# 82 条真实岗位向量，所以本地一直绿；但全新库（CI / 新克隆）里是 **0 条** ——
# 岗位向量由**导入链路**写入（`job_agent/tools/db_writer.py`），测试不跑导入，
# 于是匹配永远 0 结果、报告拿不到 3 项。这里用**确定性替身向量**补齐，
# 让链路用例不再依赖"某个库恰好被导入过"。库里本来够就完全不插手。

_ENSURE_VECTORS_PREFIX = f"ensvec_{int(time.time())}"
_EMBEDDING_DIM = 1024


async def seed_job_vectors_if_missing(minimum: int = 3) -> list[int]:
    """保证 `job_match_embeddings` 至少 `minimum` 条；返回**本次新建的岗位 id**。"""
    from app.domain.models.vector import JobMatchEmbedding
    from app.domain.services.job_persist_service import upsert_job_profile

    created: list[int] = []
    async with test_session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(JobMatchEmbedding))
        ).scalar() or 0
        if total >= minimum:
            return created

        for index in range(minimum - total):
            profile, _ = await upsert_job_profile(
                session, {"title": f"{_ENSURE_VECTORS_PREFIX}_{index}"}
            )
            session.add(
                JobMatchEmbedding(
                    job_profile_id=profile.id,
                    content=f"seed job vector {index}",
                    embedding=[0.01] * _EMBEDDING_DIM,
                )
            )
            created.append(profile.id)
        await session.commit()
    return created


async def drop_seeded_job_vectors(profile_ids: list[int]) -> None:
    """删掉 `seed_job_vectors_if_missing()` 造的数据。

    顺序不能反：`job_match_embeddings` → `job_profiles` 的外键**没有级联**，
    先删岗位会挂在 FK 上。
    """
    if not profile_ids:
        return
    from app.domain.models.job import JobProfile
    from app.domain.models.vector import JobMatchEmbedding

    async with test_session_factory() as session:
        await session.execute(
            delete(JobMatchEmbedding).where(JobMatchEmbedding.job_profile_id.in_(profile_ids))
        )
        await session.execute(delete(JobProfile).where(JobProfile.id.in_(profile_ids)))
        await session.commit()


@pytest.fixture
def ensure_job_vectors():
    """函数级：保证库里有 ≥3 条岗位向量（用完还原；本来就有则不动）。"""
    created = asyncio.run(seed_job_vectors_if_missing())
    yield
    asyncio.run(drop_seeded_job_vectors(created))
