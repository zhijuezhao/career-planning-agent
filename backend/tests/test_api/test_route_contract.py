"""全路由「错误状态」契约测试：每个接口对匿名 / 坏 id / 空 body 都必须是**受控 4xx**。

为什么单独写这一层（而不是继续加功能用例）
--------------------------------------------
现有 1400+ 用例是**逐功能**写的，覆盖不到"这条路由遇到不该来的请求会怎样"。
2026-10-04 这一轮的真实事故恰恰都落在这种**接缝**上：

* `POST /resume/upload` 同步解析 35–40 秒 vs 前端 30 秒超时 —— 每层都对，链路上必坏；
* 导入链路从不写岗位向量 → 匹配永远 0 结果 —— 同样每层都对；
* LLM 功能键没绑 → 抽取/画像/聚合全部拿到网关错误，而各工具**按设计返回骨架继续跑**，
  导入照样报 completed（静默降级）。

所以这里换一种思路：**遍历真实路由表**做体检。

1. 匿名访问受保护路由 → 必须 401/403/422；**不许 2xx（越权泄露）、不许 5xx（崩了）**；
2. 带合法 token 访问 `{id}` 类路由、给一个不存在的 id → 必须 4xx；不许 5xx；
3. 写类 `{id}` 路由 + 空 body + 不存在的 id → 必须 4xx；不许 5xx。

只断言"是**受控** 4xx"，不钉死具体码（各路由有意用了不同的受控码），
这样它长期看住接缝，又不会因为换个码就假失败。
"""

from __future__ import annotations

import re

import pytest

#: 本来就不需要 token 的路径（前缀匹配）。
PUBLIC_PREFIXES = (
    "/api/v1/auth/",  # 注册 / 登录 / 刷新
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

#: 用一个大到不可能存在的 id 替换路径参数（{id} / {job_id} / {sid} …）。
BOGUS_ID = 999_999_999

#: 受控错误的可接受集合：身份未通过 / 越权 / 找不到 / 参数不合法 / 状态冲突。
CONTROLLED_4XX = {400, 401, 403, 404, 409, 422}


def _routes() -> list[tuple[str, str]]:
    """从 **OpenAPI schema** 取 (method, path) 清单。

    为什么不用 `app.routes`：本项目的 `app` 用了自定义路由容器（`_IncludedRouter`），
    `app.routes` 里只有几个顶层对象、**遍历不到子路由** —— 实测取到 **0 条** API 路由
    （这条弯路本身也说明"清单要有自检"，见 `test_route_inventory_is_non_trivial`）。
    OpenAPI 才是"实际对外提供的接口"的唯一真相。
    """
    from app.main import app

    out: set[tuple[str, str]] = set()
    for path, operations in app.openapi().get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.add((method.upper(), path))
    return sorted(out)


ROUTES = _routes()
PROTECTED = [r for r in ROUTES if not r[1].startswith(PUBLIC_PREFIXES)]
#: 路径里带参数的（`{...}`）—— 可以用"不存在的 id"去探。
WITH_PARAM = [r for r in PROTECTED if "{" in r[1]]
GET_WITH_PARAM = [r for r in WITH_PARAM if r[0] == "GET"]
WRITE_WITH_PARAM = [r for r in WITH_PARAM if r[0] in {"POST", "PUT", "PATCH", "DELETE"}]


def _bogus(path: str) -> str:
    return re.sub(r"\{[^}]*\}", str(BOGUS_ID), path)


def _label(item: tuple[str, str]) -> str:
    return f"{item[0]} {item[1]}"


def test_route_inventory_is_non_trivial():
    """路由清单本身要合理 —— 防止"路由全没了"这种灾难被静默通过。"""
    assert len(ROUTES) >= 80, f"路由数异常偏少：{len(ROUTES)}"
    assert len(PROTECTED) >= 60, f"受保护路由异常偏少：{len(PROTECTED)}"


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=[_label(r) for r in PROTECTED])
def test_anonymous_request_is_rejected(client, method, path):
    """匿名访问必须被**受控拒绝**：不许 2xx（越权），不许 5xx（崩了）。"""
    resp = client.request(method, _bogus(path), json={})
    assert resp.status_code in CONTROLLED_4XX, (
        f"匿名 {method} {path} → {resp.status_code}（期望 {sorted(CONTROLLED_4XX)}）；"
        f"body={resp.text[:200]}"
    )


@pytest.mark.parametrize(("method", "path"), GET_WITH_PARAM, ids=[_label(r) for r in GET_WITH_PARAM])
def test_get_with_unknown_id_is_controlled_4xx(client, admin_token, student_token, method, path):
    """`{id}` 不存在时必须是受控 4xx —— 尤其是**不许 5xx**（那说明没处理 None）。"""
    token = admin_token if path.startswith("/api/v1/admin/") else student_token
    resp = client.get(path.replace(re.search(r"\{[^}]*\}", path).group(), str(BOGUS_ID)),
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in CONTROLLED_4XX, (
        f"{method} {path} (id 不存在) → {resp.status_code}；body={resp.text[:200]}"
    )


@pytest.mark.parametrize(
    ("method", "path"), WRITE_WITH_PARAM, ids=[_label(r) for r in WRITE_WITH_PARAM]
)
def test_write_with_unknown_id_is_controlled_4xx(
    client, admin_token, student_token, method, path
):
    """写类路由 + 不存在的 id + 空 body：必须受控 4xx（校验失败/找不到都行，**不许 5xx**）。

    用"不存在的 id"是为了让"找不到"先于任何副作用 —— 所以这条用例**不会改数据**。
    """
    token = admin_token if path.startswith("/api/v1/admin/") else student_token
    resp = client.request(
        method,
        _bogus(path),
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in CONTROLLED_4XX, (
        f"{method} {path} (id 不存在) → {resp.status_code}；body={resp.text[:200]}"
    )


def test_openapi_schema_is_served(client):
    """`/openapi.json` 必须能生成 —— 响应模型写坏（如循环引用）会在这里炸。"""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    assert len(resp.json().get("paths", {})) >= 40
