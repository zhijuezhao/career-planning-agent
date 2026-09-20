#!/usr/bin/env python
"""幂等创建 / 修复管理员账号（解决"第一个管理员从哪来"）。

脚本放在 backend/scripts/ 下，两种运行方式都可达：

    # ① 宿主机（连宿主机 5432）
    python backend/scripts/seed_admin.py --username admin --password 'YourPass123'

    # ② 容器内（连 compose 的 postgres 服务；容器只挂载了 ./backend）
    docker compose exec backend python scripts/seed_admin.py --username admin --password 'YourPass123'

    # 也可以用环境变量
    ADMIN_USERNAME=admin ADMIN_PASSWORD=YourPass123 python backend/scripts/seed_admin.py

行为：
    * 用户不存在 → 必须提供密码，否则退出码 2（拒绝用默认弱口令建号）
    * 用户已存在 → 提权 role=admin、status=1；仅在给了 --password 时才改密
    * 幂等：重复执行结果一致

Windows 控制台若中文乱码，先执行: chcp 65001
数据库地址优先级：--database-url > 环境变量 DATABASE_URL > .env > 内置默认值
（仓库根 .env 是生产模板、含 Settings 未声明的键，解析失败时会回退并告警，不会崩）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 先把工作目录切到 backend/：app.infrastructure.database 在【模块级】就调用
# get_settings()，而 get_settings() 按 CWD 读 .env —— 仓库根 .env 是生产模板，
# 含 Settings 未声明的键，pydantic-settings 会 extra_forbidden 直接崩。
# 切到 backend/ 后读的是 backend/.env（容器内 CWD 本来就是 /app/backend，等价）。
os.chdir(BACKEND_DIR)

from app.domain.models.user import User  # noqa: E402
from app.infrastructure.security import hash_password  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_planning"


def resolve_database_url(cli_value: str | None) -> tuple[str, str]:
    """返回 (数据库 URL, 来源说明)。"""
    if cli_value:
        return cli_value, "--database-url"
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"], "环境变量 DATABASE_URL"
    try:
        from app.config import get_settings

        return get_settings().database_url, ".env / get_settings()"
    except Exception as exc:  # noqa: BLE001 - .env 不可用不应导致脚本崩溃
        print(
            f"[WARN] 读取 .env 失败（{type(exc).__name__}），回退到内置默认连接串；"
            "如需指定请用 --database-url",
            file=sys.stderr,
        )
        return DEFAULT_DATABASE_URL, "内置默认值（回退）"


async def seed_admin(database_url: str, username: str, password: str | None) -> int:
    # 自带 engine + NullPool：避免池化连接跨事件循环复用（同 tests/conftest.py 的坑）
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            user = (
                await session.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()

            if user is None:
                if not password:
                    print(
                        f"[FAIL] 用户 {username!r} 不存在；创建管理员必须提供 --password"
                        "（拒绝使用默认弱口令）",
                        file=sys.stderr,
                    )
                    return 2
                user = User(
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    status=1,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                print(
                    f"[OK] 已创建管理员 id={user.id} username={user.username} "
                    f"role={user.role} status={user.status}"
                )
                return 0

            changes: list[str] = []
            if user.role != "admin":
                user.role = "admin"
                changes.append("role->admin")
            if user.status != 1:
                user.status = 1
                changes.append("status->1")
            if password:
                user.password_hash = hash_password(password)
                changes.append("已重置密码")

            if not changes:
                print(f"[SKIP] {username!r} 已是管理员且无需变更（幂等）")
                return 0

            await session.commit()
            print(f"[OK] 已更新 id={user.id} username={user.username}：" + "、".join(changes))
            return 0
    finally:
        await engine.dispose()


def _mask(database_url: str) -> str:
    """隐藏连接串里的账号密码后再打印。"""
    if "@" in database_url:
        return "..." + database_url[database_url.index("@"):]
    return database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="幂等创建 / 修复管理员账号")
    parser.add_argument(
        "--username", default=os.environ.get("ADMIN_USERNAME", "admin"), help="管理员用户名"
    )
    parser.add_argument(
        "--password", default=os.environ.get("ADMIN_PASSWORD"), help="管理员密码（建号必填）"
    )
    parser.add_argument("--database-url", default=None, help="默认取 DATABASE_URL 或 .env")
    args = parser.parse_args()

    url, source = resolve_database_url(args.database_url)
    print(f"[INFO] 目标数据库 {_mask(url)}  (来源: {source})")
    try:
        return asyncio.run(seed_admin(url, args.username, args.password))
    except Exception as exc:  # noqa: BLE001 - CLI 入口：任何异常都要给出可读信息
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
