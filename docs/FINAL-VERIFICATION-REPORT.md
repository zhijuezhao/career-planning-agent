# 最终验收报告（收尾工作）

> 承接 `docs/HANDOFF-2026-10-04-import-pipeline-b1-b5.md`（B1–B5 改了什么）
> 与 `docs/HANDOFF-2026-10-04-db-acceptance-and-fixes.md`（DB 验收 + 三个真事故）。
> 本文件是**收尾验收**的事实记录：做了什么、实测指标、发现的问题、遗留项。
> 所有数字都是本机实测，**没有估算**。

---

## 0. 三批任务的完成情况

| # | 任务 | 提交 | 状态 |
|---|---|---|---|
| 1 | B1–B5 岗位导入链路（切片闸门 / 分等级聚合 / 技能维度） | `e4ffefe` | ✅ 已提交 |
| 2 | 简历「解析失败」修复（前端 30s 超时 < 后端同步解析 35–40s；重复上传复用） | `cbe39d5` | ✅ 已提交 |
| 3 | 岗位向量缺失修复（聚合落库即写向量 + `backfill_job_embeddings.py`） | `307238a` | ✅ 已提交 |
| 4 | 本轮：路由/错误状态契约测试、端到端业务链路测试、数据相关测试修正、分类器补全 | 见 §5 | ✅ 已提交 |

**未做**（交接里明确列为"可选/未要求"）：词表补全、等级适配信号、老数据 payload 补跑。

---

## 1. 链路验收：真实活体（非 mock）实测

脚本：本地验收脚本（拷到容器内跑），用一份 **307,436 字节的测试简历 PDF**（临时注册的用户，跑完即由脚本清理）。
结果：**9/9 项通过**。

| 步骤 | 结果 | 实测指标 |
|---|---|---|
| 注册 + 登录 | PASS | HTTP 200 |
| 简历上传 + **真实 LLM 解析** | PASS | HTTP 202、resume_id=358、**35.0 秒**、五层 `hard_skills/intention/practice/soft_skills/traits` 齐全、六维有 |
| 回填 resume_form | PASS | HTTP 200、9 个字段 |
| 快照生成（**真实 embedding**） | PASS | snapshot_id=983、1.0 秒、`has_embedding=True`、六维冻结 6 项 |
| 人岗匹配（**真实岗位向量**，前端默认 `max_distance=0.65`） | PASS | HTTP 200、**total=10**、返回 3 条、**0.1 秒**、top 分数 0.805/0.802/0.802 |
| 规划报告生成 | PASS | HTTP 200、record_id=216、**正文 3521 字**、30.4 秒 |
| 报告列表 / 详情 / 下载 Word | PASS | 列表 1 条、详情 3521 字、HTTP 200、**docx 41,230 字节** |
| 错误状态：只给 2 项匹配 | PASS | **HTTP 422** + `matching_results 必须恰为 3 项` |
| 错误状态：不存在的快照 | PASS | **HTTP 404** |

临时用户及其简历已清理（脚本自带 cleanup）。

---

## 2. 自动化测试：新增两层"接缝"测试

现有 1400+ 用例是**逐功能**写的，覆盖不到"这条路由遇到不该来的请求会怎样"。
2026-10-04 修的三处问题全都出在这种接缝上，所以新增：

### 2.1 `tests/test_api/test_route_contract.py`（**152 passed**）

遍历 **OpenAPI schema** 的全部接口（103 条 method+path），三条契约：

1. **匿名访问受保护路由** → 必须 401/403/422；**不许 2xx（越权）、不许 5xx（崩了）**；
2. **带合法 token 访问 `{id}` 路由 + 不存在的 id** → 必须受控 4xx；不许 5xx；
3. **写类 `{id}` 路由 + 空 body + 不存在的 id** → 必须受控 4xx；不许 5xx。
   另有 `test_route_inventory_is_non_trivial`（路由数 <80 直接红）与 `/openapi.json` 可生成。

> 踩坑记录：第一版用 `app.routes` 遍历，**取到 0 条**（本项目 `app` 用自定义路由容器
> `_IncludedRouter`，子路由不在 `app.routes` 里）→ 改用 `app.openapi()["paths"]`。
> 幸好加了"清单非空"自检，否则这层会**静默空跑**。

### 2.2 `tests/test_api/test_e2e_business_chain.py`（**11 passed**，44 秒）

一条链跑通：**注册 → 上传简历 → 解析 → 回填 → 快照 → 匹配 → 报告生成 → 列表/详情/下载**，
并对每步断言**数据形状** + **错误状态**（2 项匹配 422、不存在快照 404、不存在记录 404、未知任务 404）。

* 简历解析 LLM 与快照 embedding 用**确定性替身**（零网络/零计费/可复现），embedding 维度按 DB 契约取 **1024**；
* 匹配用 `max_distance=2.0`（余弦距离上界）+ `top_k=10` → 与替身向量取值无关地保证"有 ≥3 条岗位向量就必有 ≥3 条候选"，从而把链路推到报告那一步；
* 踩坑记录：`TestClient` **必须用 `with` 上下文**才复用同一个事件循环，否则 `asyncio.ensure_future`
  排的快照后台任务永远推进不了（实测轮询 12 秒一直 `running`）。

---

## 3. 修掉的"真实功能缺口"与"测试自身的问题"

### 3.1 真实功能缺口：岗位标题分类器覆盖不到真实数据（已修）

`app/core/chat/workflows.py::classify_title` 的类目原本是**技术岗视角**
（算法/AI、数据、测试、前端/客户端/游戏、运维/网络/安全/支持、项目/管理/实施、售前/客户、
高管/架构、文档、后端/语言）。真实导入的智联招聘表以**销售 / 客服 / 运营 / 法务 / 翻译 /
行政**为主 —— 实测 47 个真导入岗位名里 **34 个落进「其他」**。

后果：学生问"有哪些销售岗"时，岗位分布图会把这 34 个岗位全塞进一个兜底桶，等于该模块
对真实数据不可用。

修法：**在原有技术类目之后**追加 9 个业务类目（客服/审核、销售/BD/推广、法务/合规/知识产权、
翻译/语言、培训/教育、科研/质量/统计、运营/市场、人力/行政、咨询/招投标），共 19 个类目。
顺序即优先级，追加在最后保证**不改动既有归类**；并特意处理了三处会互相抢词的顺序
（"内容审核"不能被"内容"抢、`律师助理`不能被"助理"抢、`猎头顾问`不能被"顾问"抢）。

**实测：47/47 真实岗位名全部可归类，未归类 0。**

### 3.2 测试自身的问题（不是业务 bug，但会让"检查不出问题"）

| 文件 | 问题 | 修法 |
|---|---|---|
| `test_core/test_config.py` | 6 个 `test_default_*` 断言"代码默认值"，却读 `backend/.env`（本机 `LLM_FALLBACK_ORDER=longcat`）→ 必红 | 改成 `Settings(_env_file=None)`，真正测默认值 |
| `test_core/test_career_fields.py` | ① 写死 `expected[field_name]` → 源文本没有该标签时 `KeyError`（**测试 bug**）；② 要求所有导入岗位 `career_path/transition_paths` 非空 —— 那是**职业发展路线表**专属假设 | 改为**双向对账**（源里有→库里逐字一致；源里没有→库里必须为空），带标签的条数为 0 时明确 skip 并说明原因。实测该数据集：`岗位晋升/换岗方向/所需证书` 标签为 0 处（回填脚本 dry-run 也是「可解析 0 处」），三列全空是**正确**的 |
| `test_api/test_admin_jobs.py` | 地域用例断言"新疆全省只有 1 条"，被真实导入的岗位打破 | 改成"筛得到本用例那条"，并加负例（同市不同区不出现） |
| `tests/test_api/test_admin_companies.py` | 断言列表前 20 条 = 我造的两家；真实 87 家公司按 `job_count` 排序把「乙」挤出分页 | 加 `q=<本用例前缀> & limit=100` 收敛候选 + 全页降序性质断言 |
| `tests/test_core/test_agent_readonly_tools.py` | 关键词/地域断言 `total == 1`，被真实岗位打破（实测 total=5 / 13） | 改为"我这条必须在结果里" + 用唯一前缀做**更严**的精确断言（大小写/空格归一化失效会直接红） |
| `tests/conftest.py::db_session` | 用应用的**池化** `async_session_factory`，连接跨事件循环 → teardown 报 `Event loop is closed` | 改用 conftest 的 `test_session_factory`（NullPool，本文件自己记录的既定口径）。**注**：该 teardown ERROR 仍存在（见 §4.3），此改动只是与既定口径对齐 |

---

## 4. 仍存在的问题（如实列出，未修）

### 4.1 `test_journey_status.py` 的 teardown ERROR（测试基建）
`test_snapshot_no_report_returns_guide` **用例本身通过**，但 teardown 报
`RuntimeError: Event loop is closed` —— pytest-asyncio 的 async fixture finalizer 在**另一个
事件循环**里跑 `session.close()`。NullPool 也救不了（连接对象本身属于已关闭的 loop）。
彻底修需要统一 pytest-asyncio 的 loop 作用域（`asyncio_default_fixture_loop_scope`），
但那会影响全部 1400+ 异步用例，**风险大于收益**，故记录不修。

### 4.2 逐片去重看不到跨片重复
真实表 524 行里 `岗位编码` 只有 487 个唯一值，而去重是**逐片**做的 → 跨片重复编码会被保留。
"不丢数据"的方向是对的，但交接文档里"524→487"这个基线**在切片模式下不成立**
（实测落库按"通过质检的 398 行"）。

### 4.3 `node_persist` 与聚合各写一份画像
`node_persist` 逐行 upsert 出 `(岗位, 不限)`，聚合再写 `(岗位, 中级/初级/高级)` →
同一个岗位名可能同时有"真画像"和"骨架画像"。实测 87 条里 12 条是 persist 留下的骨架
（六维全 `{"score": 3}`、技能空、无综合卡）。**建议删掉或让两方只由一方写。**

### 4.4 `job_aggregate` 不是已注册的功能键
`FUNCTION_KEYS` 只有 `default / job_quality / job_extract / job_portrait / job_link_extract /
resume_parse / embedding` → **聚合只能靠 `default`**。建议注册 `job_aggregate` 或把 `default` 绑稳。

### 4.5 每次聚合重跑都会重算该组岗位向量
87 组 ≈ 87 次 embedding 调用（便宜但非零）。要省就在 `embed_job` 加"内容没变就跳过"
（`scripts/backfill_job_embeddings.py` 已有这套判断，可抽成共用）。

### 4.6 简历解析仍是**同步**接口
后端同步解析实测 **35 秒**，前端已把这次请求超时放宽到 180 秒（后端另有按 `content_hash`
复用兜底）。更正确的形态是 `202 + task_id 轮询`（照 `/profile/snapshot` 那套）。

### 4.7 admin 端上传同样是 30 秒超时 + 同步切片
`frontend/admin/src/api/request.ts` 超时 30 秒，而 `POST /admin/import/upload`（上传即切片）
是同步的 —— 大文件同类风险，未改。

---

## 5. 本轮提交与文件清单

| 提交 | 内容 |
|---|---|
| `307238a` | 岗位向量修复（聚合落库写向量 + backfill 脚本 + 测试） |
| 本轮提交（见 `git log -1`） | 新增 `test_route_contract.py`、`test_e2e_business_chain.py`；修 `workflows.py`（分类器补 9 个业务类目）；修 `test_config.py` / `test_career_fields.py` / `test_admin_companies.py` / `test_agent_readonly_tools.py` / `test_admin_jobs.py` / `conftest.py` |

---

## 6. 环境事实（复现时注意）

* **Docker Desktop 不在标准路径**：`%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe`
  （本轮中途 Docker 曾停止，需重新启动 + `docker compose up -d postgres redis backend`）。
* 后端容器内 **8001**、宿主 **8002**；nginx 80（`proxy_read_timeout 300s`）。
* 库内产品数据：**87 条岗位画像 + 87 条岗位向量 + 399 条原始行**（真实比赛数据）。
* LLM 路由（dev 库 `llm_routes`）：`default`/`job_extract`/`job_portrait`/`job_quality` → model 215
  （`longcat:LongCat-2.0`）；`embedding` 未绑 → 回退 env（`text-embedding-v4`，1024 维，实测可用）。
## 7. 最终全量测试结果（全部修复后）

```
2 failed, 1593 passed, 128 skipped, 1 error in 380.84s (0:06:20)
```

| 项 | 数量 | 说明 |
|---|---|---|
| passed | **1593** | 比修之前多 168（新增路由契约 152 + 端到端链路 11 + 分类器等修正带来的绿化） |
| skipped | 128 | 多为"库里没有可追溯数据/数据集不适用"的显式跳过（都写了原因） |
| failed | **2** | 均为**测试自身残留数据**造成：`test_admin_dashboard::TestImportOverviewP16`（统计全库工单数）与 `test_score_deriver::test_tool_ainvoke_writes_to_db`（顺序相关）。**清掉测试残留后单独复跑：2 passed** ✓ |
| error | 1 | `test_journey_status` 的 **teardown** ERROR（用例本身通过）→ §4.1 |

结论：**没有代码层面的红灯**。红的两条是"同一个 dev 库既装真实数据又跑测试"这一固有矛盾，
已在本报告 §3.2 / §6 记录清楚（跑完测试要清库）。

