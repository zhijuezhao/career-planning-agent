# 被取代的前端页面（归档）

本目录存放**成长旅程重构（2026-09-14 计划）之前**的学生端页面实现。
它们已不在 `frontend/student/src/router/index.ts` 的路由表中，全仓零引用，
移出 `src/` 是为了不再参与 `vue-tsc` 编译（`tsconfig.app.json` 的 `include` 覆盖整个 `src/**`）。

## CareerView.vue（原 `frontend/student/src/views/career/CareerView.vue`）

- **归档时间**：2026-09-19（Task 16 收口）
- **为何不迁移**：该页依赖 `careerApi.getPaths/getPlans/generatePath/generatePlan`
  → 对应后端 `/api/v1/career/paths`、`/api/v1/career/plans` 在 Admin 清理块中已**全部改为 501 桩**
  （`backend/app/api/v1/career.py` 实测 6 个 501），端点与数据表（`GrowthPath`/`GrowthPlan`）均已删除，
  因此该页**无法迁移到新契约**。
- **功能归属**：其职责已由 `frontend/student/src/views/business/CareerView.vue`（职业报告）
  与 `views/business/DashboardView.vue`（总览/历史）取代。
- **保留原因**：工作区中存在约 1045 行未提交实现（HEAD 仅为 45 行占位），
  按「不擅自丢弃他人未提交工作」的准则归档留存，而非直接删除。

## 其余已迁移页面（仍在 `src/`，仅改数据层）

以下页面同样不在路由表中，但依赖的端点仍存活，已在 Task 16 迁移到新契约后保留：

| 文件 | 迁移内容 |
|---|---|
| `views/jobs/JobsView.vue` | 仅清理未使用导入 |
| `views/profile/ProfileView.vue` | 修正 `layerConfig` 键类型（消除 TS7053）+ 清理未使用项 |
| `views/report/ReportView.vue` | 旧 `/reports` 契约 → `/reports/records`；`report_content` → `report_text`（改用 `ReportMarkdown`）；`target_job` 输入改为描述筛选；生成入参改为 `profile_snapshot_id` + 本地 3 项匹配结果 |
| `views/matching/MatchingView.vue` | 旧 `/matching/results`+`/feedback`（已删） → 本地收藏；`profile_id` → `profile_snapshot_id`；移除无端点的历史区块 |

> 若后续确认这些页面无需保留，可直接删除；若需要恢复为路由可达页面，请先确认对应后端端点存在。
