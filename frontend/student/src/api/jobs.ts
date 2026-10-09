/**
 * 岗位列表 API 模块
 * 封装岗位列表查询、岗位详情获取等接口
 * 对应后端 API: GET /api/v1/jobs
 */

import request from './request'

// ==================== 类型定义 ====================

/** 岗位画像响应 */
export interface JobProfileResponse {
  id: number
  title: string
  industry: string | null
  level: string | null
  hard_skills: Record<string, any> | null
  soft_skills: Record<string, any> | null
  salary_range: string | null
  education_requirement: string | null
  experience_requirement: string | null
  career_path: Record<string, any> | null
  transition_paths: Record<string, any> | null
  requirement_intensity: Record<string, any> | null
  outlook: Record<string, any> | null
  summary: string | null
  source_data_ids: Record<string, any> | null
  created_at: string
  updated_at: string
}

/** 岗位列表响应 */
export interface JobListResponse {
  total: number
  items: JobProfileResponse[]
}

/** 岗位列表查询参数 */
export interface JobListParams {
  skip?: number
  limit?: number
  industry?: string
  level?: string
  keyword?: string
}

// ==================== API 方法 ====================

export const jobsApi = {
  /**
   * 获取岗位列表
   * GET /api/v1/jobs
   */
  getList: (params?: JobListParams) => request.get<any, JobListResponse>('/jobs', { params }),

  /**
   * 获取单个岗位详情
   * GET /api/v1/jobs/{job_id}
   */
  getDetail: (jobId: number) => request.get<any, JobProfileResponse>(`/jobs/${jobId}`),
}
