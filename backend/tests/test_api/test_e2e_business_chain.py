"""端到端业务链路测试：**注册 → 登录 → 简历上传 → 解析 → 快照 → 匹配 → 报告生成**。

为什么必须有这一层
------------------
2026-10-04 这一轮修的三处问题，没有一个是"某个函数写错了"：

* 简历上传：后端同步解析 35–40 秒、前端 axios 超时 30 秒 → 用户看到"解析失败"，
  而后端其实成功落库（**步骤之间**的契约不一致）；
* 岗位向量：匹配只读 `job_match_embeddings`，而导入链路从不写它 → 匹配永远 0 结果
  （每一步都对，**链路**不通）；
* LLM 功能键没绑：抽取/画像/聚合拿到网关错误却**按设计返回骨架**继续跑 → 导入报成功。

所以链路要一条条步骤真跑，并在每一步同时断言：**正常路径的数据形状** +
**错误状态是否可检查**（不许把失败伪装成成功）。

设计取舍
--------
* 简历解析的 LLM、以及快照的 embedding 都换成**确定性替身**：不联网、不计费、可复现。
  embedding 维度必须是 **1024**（DB 列 `vector(1024)`），替身也照此返回。
* 匹配用 `max_distance=2.0`（余弦距离上界）+ `top_k=10`：**与向量内容无关**地保证
  "库里有 ≥3 条岗位向量就必然拿到 ≥3 条候选"，从而把链路推到报告生成那一步；
  这不算"放宽标准"—— 距离阈值本身另有用例（前端默认 0.65）。
* 真实（非替身）活体链路的实测数字见 `docs/FINAL-VERIFICATION-REPORT.md`。
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

#: 极简但**合法**的 PDF（`%PDF` magic + 可被 pdf 提取器打开），沿用 test_resume_api 里的字节。
MINIMAL_PDF = b"""\
%PDF-1.0
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R\
/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Hello Resume) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
434
%%EOF"""

#: 简历解析 LLM 的确定性产出。必须能通过 `ParsedResume.model_validate`（见 schemas.py）：
#: 其余字段都有默认值，所以只给必要的几个；六维分数必须落在 1~5。
FAKE_PARSED: dict = {
    "basic_info": {"name": "张三", "degree": "本科", "major": "计算机科学与技术"},
    "intention": {"target_position": ["后端工程师"], "target_city": ["北京"]},
    "hard_skills": {"tags": ["Java", "MySQL"], "certificates": ["CET-6"]},
    "dimension_scoring": {
        "profile_type": "candidate",
        "total_dim_score": 3.5,
        "dimensions": {
            "专业技术能力": {"score": 4.0, "sub_dimensions": {"编程": 4.0}},
            "实践经验背景": {"score": 3.0, "sub_dimensions": {"实习": 3.0}},
            "通用软素质": {"score": 3.5, "sub_dimensions": {"沟通": 3.5}},
            "职业匹配度": {"score": 3.0, "sub_dimensions": {"意向": 3.0}},
            "成长潜力": {"score": 3.5, "sub_dimensions": {"学习": 3.5}},
            "基础资质条件": {"score": 4.0, "sub_dimensions": {"学历": 4.0}},
        },
    },
}

EMBEDDING_DIM = 1024


class _StubEmbeddings:
    """embedding 替身：维度必须是 1024（DB 列固定 `vector(1024)`，否则写入报错）。"""

    async def aembed_query(self, _text: str) -> list[float]:
        return [0.01] * EMBEDDING_DIM

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * EMBEDDING_DIM for _ in texts]


@pytest.fixture(scope="module", autouse=True)
def offline_llm():
    """把「简历解析 LLM」与「快照 embedding」换成替身 —— 本文件零网络、零计费。"""
    from app.core.resume_agent.tools import resume_parser
    from app.domain.services import snapshot_service

    with (
        patch.object(resume_parser, "_parse_resume", new=AsyncMock(return_value=FAKE_PARSED)),
        # 注意 patch **消费方模块**里的名字：snapshot_service 是 `from ... import get_embeddings`
        patch.object(snapshot_service, "get_embeddings", lambda: _StubEmbeddings()),
    ):
        yield


@pytest.fixture(scope="module")
def live_client():
    """**必须用 `with`**：TestClient 只有在上下文管理里才复用同一个事件循环。

    不用 `with` 时每个请求各起一个阻塞 portal（各自的 loop），于是
    `POST /profile/snapshot` 里 `asyncio.ensure_future` 排的后台任务**永远推进不了** ——
    实测轮询 12 秒一直是 `running`（这正是本文件第一版踩的坑）。
    快照是异步任务 + 轮询的链路，必须给它一个活着的 loop。
    """
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def chain_headers(live_client) -> dict:
    """链路专用的学生账号（模块级唯一用户名，避免与其它测试串号）。"""
    from tests.conftest import _login, _register

    username = f"e2e_chain_{int(time.time() * 1000)}"
    password = "chain123456"
    _register(live_client, username, password)
    return {"Authorization": f"Bearer {_login(live_client, username, password)}"}


def _poll_snapshot(client, headers, task_id, tries: int = 60, interval: float = 0.2):
    """轮询快照任务直到 done/failed（与 test_profile_snapshot.py 同一手法）。"""
    for _ in range(tries):
        time.sleep(interval)
        resp = client.get(f"/api/v1/profile/snapshot/{task_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        if resp.json()["status"] in {"done", "failed"}:
            return resp
    pytest.fail(f"快照任务 {task_id} 在 {tries * interval:.0f}s 内未结束")


@pytest.fixture(scope="module")
def chain(live_client, chain_headers) -> dict:
    """把链路前半段（上传 → 回填 → 快照）真跑一遍，供后续用例共享。"""
    client, headers = live_client, chain_headers

    # ① 简历上传 + 解析（解析 LLM 已替身化）
    upload = live_client.post(
        "/api/v1/resume/upload",
        files={"file": ("e2e_chain.pdf", MINIMAL_PDF, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 202, upload.text
    parsed = upload.json()
    assert parsed["status"] == "parsed", parsed
    assert parsed["five_layers"], "解析结果必须带五层画像（不能是空骨架）"
    assert parsed["dimension_scoring"], "解析结果必须带六维评分"
    resume_id = parsed["resume_id"]

    # ② 回填 resume_form（= 前端「画像确认」页做的事：顶层平铺 + five_layers + 六维）
    six_dim_flat = {
        name: float(dim["score"]) for name, dim in parsed["dimension_scoring"]["dimensions"].items()
    }
    form = {
        **(parsed["five_layers"] or {}),
        "five_layers": parsed["five_layers"],
        "dimension_scoring": parsed["dimension_scoring"],
        "six_dim_scores": six_dim_flat,
        "resume_id": resume_id,
    }
    put = live_client.put("/api/v1/profile", json={"resume_form": form}, headers=headers)
    assert put.status_code == 200, put.text

    # ③ 生成快照（异步任务 + 轮询）
    created = live_client.post("/api/v1/profile/snapshot", headers=headers)
    assert created.status_code == 200, created.text
    poll = _poll_snapshot(client, headers, created.json()["task_id"])
    assert poll.json()["status"] == "done", poll.text
    snapshot_id = poll.json()["snapshot_id"]
    assert snapshot_id, "快照完成却没有 snapshot_id"

    return {
        "headers": headers,
        "resume_id": resume_id,
        "snapshot_id": snapshot_id,
        "parsed": parsed,
    }


class TestResumeParseStep:
    def test_parsed_resume_is_readable_for_the_user(self, live_client, chain):
        """解析结果必须**存下来并可再读**（否则"上传成功"只是幻觉）。"""
        resp = live_client.get(f"/api/v1/resume/{chain['resume_id']}", headers=chain["headers"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "parsed"
        assert body["parsed_data"], "parsed_data 不能为空"

    def test_latest_resume_points_at_the_uploaded_one(self, live_client, chain):
        resp = live_client.get("/api/v1/resume/latest", headers=chain["headers"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["resume_id"] == chain["resume_id"]

    def test_radar_is_built_from_the_parsed_scoring(self, live_client, chain):
        resp = live_client.get(f"/api/v1/resume/{chain['resume_id']}/radar", headers=chain["headers"])
        assert resp.status_code == 200, resp.text
        radar = resp.json()
        assert radar.get("indicators") and radar.get("values")
        assert len(radar["indicators"]) == len(radar["values"])


class TestSnapshotStep:
    def test_snapshot_is_listed_and_has_embedding(self, live_client, chain):
        listed = live_client.get("/api/v1/profile/snapshots", headers=chain["headers"])
        assert listed.status_code == 200, listed.text
        ids = [item["id"] for item in listed.json()]
        assert chain["snapshot_id"] in ids

        detail = live_client.get(
            f"/api/v1/profile/snapshots/{chain['snapshot_id']}", headers=chain["headers"]
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["five_layers"], "快照必须冻结五层画像"
        assert body["dimension_scores"], "快照必须冻结六维分数"
        assert body["has_embedding"] is True, "快照没有向量 → 匹配不可能有结果"

    def test_snapshot_unknown_id_is_404(self, live_client, chain):
        resp = live_client.get("/api/v1/profile/snapshots/999999999", headers=chain["headers"])
        assert resp.status_code == 404, resp.text

    def test_snapshot_poll_unknown_task_is_404(self, live_client, chain):
        resp = live_client.get("/api/v1/profile/snapshot/not-a-task", headers=chain["headers"])
        assert resp.status_code == 404, resp.text


class TestMatchingStep:
    def test_matching_returns_ranked_results(self, live_client, chain, ensure_job_vectors):
        """匹配必须真的返回候选（岗位向量存在时）。

        `max_distance=2.0` 是余弦距离的**上界**，等于"不做距离过滤"—— 这样断言与
        替身向量的取值无关（真实距离阈值另有前端默认 0.65 的用例）。

        `ensure_job_vectors`（conftest）：全新库里没有岗位向量，用它补齐 ≥3 条
        确定性替身向量；开发库本来就有 82 条时不插手。
        """
        resp = live_client.post(
            "/api/v1/matching/run",
            json={"profile_snapshot_id": chain["snapshot_id"], "top_k": 10, "max_distance": 2.0},
            headers=chain["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["profile_snapshot_id"] == chain["snapshot_id"]
        assert body["total"] >= 1, f"岗位向量存在却 0 命中：{body}"
        assert 1 <= len(body["results"]) <= 3, "results 至多返回 3 项（接口契约）"
        for item in body["results"]:
            assert item["job_profile_id"] > 0
            assert 0.0 <= item["match_score"] <= 1.0
            assert item["analysis"]["weights_used"], "匹配分析必须带权重（可解释）"

    def test_matching_on_unknown_snapshot_is_404(self, live_client, chain):
        resp = live_client.post(
            "/api/v1/matching/run",
            json={"profile_snapshot_id": 999999999, "top_k": 3, "max_distance": 2.0},
            headers=chain["headers"],
        )
        assert resp.status_code == 404, resp.text


class TestReportStep:
    def _three_results(self, live_client, chain) -> list[dict]:
        resp = live_client.post(
            "/api/v1/matching/run",
            json={"profile_snapshot_id": chain["snapshot_id"], "top_k": 10, "max_distance": 2.0},
            headers=chain["headers"],
        )
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert len(results) == 3, f"报告要求恰 3 项匹配，实际 {len(results)}：{results}"
        return [{"job_profile_id": r["job_profile_id"], "match_score": r["match_score"]} for r in results]

    def test_generate_list_detail_and_download(self, live_client, chain, ensure_job_vectors):
        payload = {
            "profile_snapshot_id": chain["snapshot_id"],
            "matching_results": self._three_results(live_client, chain),
        }
        gen = live_client.post("/api/v1/reports/generate", json=payload, headers=chain["headers"])
        assert gen.status_code == 200, gen.text
        record = gen.json()
        assert record["report_text"], "报告正文不能为空"
        assert record["version"] >= 1
        rid = record["id"]

        listed = live_client.get("/api/v1/reports/records", headers=chain["headers"])
        assert listed.status_code == 200, listed.text
        assert rid in [item["id"] for item in listed.json()]

        detail = live_client.get(f"/api/v1/reports/records/{rid}", headers=chain["headers"])
        assert detail.status_code == 200, detail.text
        assert detail.json()["report_text"] == record["report_text"]

        download = live_client.get(f"/api/v1/reports/records/{rid}/download", headers=chain["headers"])
        assert download.status_code == 200, download.text
        assert len(download.content) > 0, "下载到的 Word 不能是空文件"

    def test_two_matching_results_is_rejected(self, live_client, chain, ensure_job_vectors):
        """**错误状态要可检查**：只给 2 项必须被明确拒绝（不许"凑合生成"）。"""
        two = self._three_results(live_client, chain)[:2]
        resp = live_client.post(
            "/api/v1/reports/generate",
            json={"profile_snapshot_id": chain["snapshot_id"], "matching_results": two},
            headers=chain["headers"],
        )
        assert resp.status_code == 422, resp.text
        assert "3" in resp.text, f"错误信息应说明需要 3 项：{resp.text[:200]}"

    def test_unknown_record_is_404(self, live_client, chain):
        assert live_client.get(
            "/api/v1/reports/records/999999999", headers=chain["headers"]
        ).status_code == 404
