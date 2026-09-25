"""用户角色白名单（B2-4）—— **唯一来源**。

管理端「用户管理」需要把角色关进白名单：列表筛选传非法角色应当 422，
编辑用户传非法角色也应当 422，而不是静默返回空列表 / 往库里写一个人人不认识的角色。

`UserRole`（`typing.Literal`）既是 Pydantic / FastAPI 的校验类型，也是运行时元组
`USER_ROLES` 的来源（`get_args`）—— 两者不可能漂移。新增角色时**只改这一处**。

与数据库现状一致（`SELECT role, count(*) FROM users GROUP BY role` → student / admin）。
前端 `frontend/admin/src/views/Users.vue` 的角色选项需与本文件保持同步。
"""

from typing import Literal, get_args

USER_ROLE_STUDENT = "student"
USER_ROLE_ADMIN = "admin"

#: 允许出现在 users.role 与接口入参里的角色
UserRole = Literal["student", "admin"]

#: 运行时白名单元组（与 UserRole 同源；供非类型校验位置使用）
USER_ROLES: tuple[str, ...] = get_args(UserRole)

#: 注册用户的默认角色
DEFAULT_USER_ROLE = USER_ROLE_STUDENT


def is_valid_role(role: str | None) -> bool:
    """`role` 是否属于白名单（`None` 视为非法）。"""
    return role in USER_ROLES
