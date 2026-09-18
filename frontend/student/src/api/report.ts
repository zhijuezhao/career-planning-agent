/**
 * 生涯报告 API 模块（报告记录 records 新契约）
 * 对应后端 API: /api/v1/reports/*
 *
 * 契约要点（Task 6 后端实现）：
 * - POST /reports/generate 要求 matching_results **恰 3 项**，否则 422
 * - version 由后端按 created_at/id 顺序计算（不是自增列）
 * - Word 为惰性生成：未下载过时 word_file_path 为 null
 * - GET /reports/records 返回数组（非 {total, items}）
 */

import request from './request'

// ==================== 类型定义 ====================

/** 报告生成请求体中的单条匹配结果 */
export interface MatchResultInput {
  job_profile_id: number
  match_score: number
}

/** 报告生成请求（matching_results 恰 3 项） */
export interface ReportGenerateRequest {
  profile_snapshot_id: number
  matching_results: MatchResultInput[]
}

/** 报告记录（列表项，无 report_text） */
export interface ReportRecord {
  id: number
  user_id: number
  profile_snapshot_id: number
  serial_no: string
  description: string
  version: number
  created_at: string
}

/** 报告记录详情（含 report_text + 惰性 Word 路径） */
export interface ReportRecordDetail extends ReportRecord {
  report_text: string
  word_file_path: string | null
}

// ==================== API 方法 ====================

export const reportApi = {
  /**
   * 生成报告记录（冻结快照 + 恰 3 项匹配结果 → 6 模块文本入库）
   * POST /api/v1/reports/generate
   */
  generateReport: (body: ReportGenerateRequest): Promise<ReportRecordDetail> =>
    request.post<any, ReportRecordDetail>('/reports/generate', body),

  /**
   * 当前用户的报告记录列表（倒序）
   * GET /api/v1/reports/records
   */
  getRecords: (): Promise<ReportRecord[]> =>
    request.get<any, ReportRecord[]>('/reports/records'),

  /**
   * 报告记录详情
   * GET /api/v1/reports/records/{id}
   */
  getRecord: (id: number): Promise<ReportRecordDetail> =>
    request.get<any, ReportRecordDetail>(`/reports/records/${id}`),

  /**
   * 下载报告 Word（惰性生成）
   * GET /api/v1/reports/records/{id}/download
   */
  downloadWord: (id: number) =>
    request.get<any, Blob>(`/reports/records/${id}/download`, { responseType: 'blob' }),
}
