/**
 * 人岗匹配 API 模块（成长旅程新契约）
 * 对应后端 API: POST /api/v1/matching/run
 *
 * 契约要点（Task 5 后端实现，逐字核对 job_matcher.compute_match_score）：
 * - match_score / vector_similarity / dimension_score / match_ratio 均为 **0~1** 比例值
 * - dimension_matches[维度] = { user_score, job_score, weight, match_ratio }
 * - results 恰 3 项（后端 results[:3]），total 为完整排名条数
 */

import request from './request'

// ==================== 类型定义 ====================

/** 单维度匹配详情（0~1 比例值） */
export interface DimensionMatchDetail {
  user_score: number
  job_score: number
  weight: number
  match_ratio: number
}

/** 匹配分析 */
export interface MatchAnalysis {
  vector_similarity: number
  dimension_score: number
  dimension_matches: Record<string, DimensionMatchDetail>
  weights_used: Record<string, number>
}

/** 匹配结果项 */
export interface MatchResultItem {
  job_profile_id: number
  match_score: number
  distance: number
  analysis: MatchAnalysis
}

/** 匹配执行请求 */
export interface MatchRunRequest {
  profile_snapshot_id: number
  top_k?: number
  max_distance?: number
}

/** 匹配执行响应（results 恰 3 项） */
export interface MatchRunResponse {
  user_id: number
  profile_snapshot_id: number
  total: number
  results: MatchResultItem[]
}

// ==================== API 方法 ====================

export const matchingApi = {
  /**
   * 执行人岗匹配（读快照 embedding + 冻结六维分数）
   * POST /api/v1/matching/run
   * @param profileSnapshotId 快照 ID
   * @param topK 候选池大小（后端截取 top3 返回）
   */
  runMatch: (profileSnapshotId: number, topK = 10): Promise<MatchRunResponse> =>
    request.post<any, MatchRunResponse>('/matching/run', {
      profile_snapshot_id: profileSnapshotId,
      top_k: topK,
    }),
}
