/**
 * 能力画像 API 模块
 * 封装画像数据获取、维度评分查询等接口
 * 画像数据来源于简历解析，通过 resume 端点获取
 * 对应后端 API: /api/v1/resume/latest, /api/v1/resume/{id}
 */

import request from './request'

// ==================== 类型定义 ====================

/** 五层能力画像数据 */
export interface AbilityProfileData {
  intention: Record<string, any>       // 意向层：目标行业/岗位/薪资/城市
  traits: Record<string, any>          // 特质层：性格/擅长方向/价值观
  practice: Record<string, any>        // 实践层：实习/项目/竞赛/校园
  soft_skills: Record<string, any>     // 软技能层：沟通/抗压/学习/创新/协作
  hard_skills: Record<string, any>     // 硬技能层：专业技能/证书/学历/成绩
}

/** 维度评分项 */
export interface DimensionScoreItem {
  top_dimension: string       // 顶层维度（中文）
  sub_dimension: string       // 子维度（中文）
  score: number               // 评分（1-5）
  weight: number              // 权重
}

/** 雷达图数据 */
export interface RadarOption {
  indicators: { name: string; max: number }[]
  values: number[]
  total_score: number
}

/** 简历状态响应（含画像关联） */
export interface ResumeStatusResponse {
  resume_id: number
  status: string
  error_message: string | null
  profile_id: number | null
  created_at: string
  updated_at: string
}

/** 简历详情响应（含解析数据） */
export interface ResumeDetailResponse {
  resume_id: number
  file_name: string
  status: string
  page_count: number | null
  parsed_data: Record<string, any>  // 包含五层画像 + 维度评分
  profile_id: number | null
  error_message: string | null
  created_at: string
  updated_at: string
}

/** POST /resume/upload 返回（Task 3：解析-only，202） */
export interface UploadParseResult {
  resume_id: number
  status: string                 // "parsed"
  five_layers: AbilityProfileData | null
  dimension_scoring: DimensionScoring | null
}

/** 六维评分子项（TOP_DIMENSIONS 之一） */
export interface SubDimensionScores {
  score: number
  sub_dimensions: Record<string, number>
}

/** 六维评分（后端 DimensionScoring 契约） */
export interface DimensionScoring {
  profile_type: string
  total_dim_score: number
  dimensions: Record<string, SubDimensionScores>
}

/** GET/PUT /profile（resume_form 单一权威来源） */
export interface ProfileResponse {
  resume_form: Record<string, any>
}

/** POST /profile/snapshot */
export interface SnapshotCreateResponse {
  task_id: string
}

/** GET /profile/snapshot/{task_id} 轮询 */
export interface SnapshotPollResponse {
  status: string                 // "running" | "done" | "failed"
  message: string | null
  snapshot_id: number | null
}

/** GET /profile/snapshots 列表项 */
export interface SnapshotSummary {
  id: number
  serial_no: string
  description: string
  created_at: string
}

/** GET /profile/snapshots/{id} 详情（永不返回 embedding 向量） */
export interface SnapshotDetail {
  id: number
  serial_no: string
  description: string
  created_at: string
  form: Record<string, any>
  five_layers: Record<string, any>
  dimension_scores: Record<string, any>
  has_embedding: boolean
}

/** 轮询结果（视图层用；非后端响应体） */
export type SnapshotPollResult =
  | { ok: true; snapshotId: number }
  | { ok: false; message: string }

// ==================== API 方法 ====================

export const profileApi = {
  /**
   * 获取最新简历状态（含 profile_id）
   * GET /api/v1/resume/latest
   */
  getLatestResume: (): Promise<ResumeStatusResponse> =>
    request.get<any, ResumeStatusResponse>('/resume/latest'),

  /**
   * 获取简历详情（含 parsed_data 五层画像）
   * GET /api/v1/resume/{resume_id}
   */
  getResumeDetail: (resumeId: number): Promise<ResumeDetailResponse> =>
    request.get<any, ResumeDetailResponse>(`/resume/${resumeId}`),

  /**
   * 获取雷达图数据
   * GET /api/v1/resume/{resume_id}/radar
   * 返回 { indicators, values, total_score }（可直接喂给 <RadarChart :data>）
   */
  getRadarData: (resumeId: number): Promise<RadarOption> =>
    request.get<any, RadarOption>(`/resume/${resumeId}/radar`),

  /**
   * 上传简历并解析（解析-only，后端同步返回结果）
   * POST /api/v1/resume/upload
   * ⚠️ 后端仅接受 PDF（校验后缀 + %PDF magic + max_upload_size_mb）
   */
  uploadResumeForParse: (file: File): Promise<UploadParseResult> => {
    const fd = new FormData()
    fd.append('file', file)
    return request.post<any, UploadParseResult>('/resume/upload', fd)
  },

  /**
   * 读取 resume_form（单一权威来源）
   * GET /api/v1/profile
   */
  getProfile: (): Promise<ProfileResponse> =>
    request.get<any, ProfileResponse>('/profile'),

  /**
   * 整表覆盖 resume_form
   * PUT /api/v1/profile
   */
  updateProfile: (resumeForm: Record<string, any>): Promise<ProfileResponse> =>
    request.put<any, ProfileResponse>('/profile', { resume_form: resumeForm }),

  /**
   * 发起异步快照生成，返回 task_id
   * POST /api/v1/profile/snapshot
   */
  createSnapshot: (): Promise<SnapshotCreateResponse> =>
    request.post<any, SnapshotCreateResponse>('/profile/snapshot'),

  /**
   * 轮询快照任务直到 done/failed 或超时
   * GET /api/v1/profile/snapshot/{task_id}
   * @param timeoutSec 总超时秒数（默认 20）
   * @param intervalMs 轮询间隔毫秒（默认 1000）
   */
  pollSnapshot: async (
    taskId: string,
    timeoutSec = 20,
    intervalMs = 1000,
  ): Promise<SnapshotPollResult> => {
    const deadline = Date.now() + timeoutSec * 1000
    while (Date.now() < deadline) {
      const res = await request.get<any, SnapshotPollResponse>(`/profile/snapshot/${taskId}`)
      if (res.status === 'done') {
        if (res.snapshot_id == null) return { ok: false, message: '快照任务完成但缺少 snapshot_id' }
        return { ok: true, snapshotId: res.snapshot_id }
      }
      if (res.status === 'failed') {
        return { ok: false, message: res.message || '快照生成失败' }
      }
      await new Promise(resolve => setTimeout(resolve, intervalMs))
    }
    return { ok: false, message: `快照生成超时（${timeoutSec}s）` }
  },

  /**
   * 快照列表（倒序）
   * GET /api/v1/profile/snapshots
   */
  getSnapshots: (): Promise<SnapshotSummary[]> =>
    request.get<any, SnapshotSummary[]>('/profile/snapshots'),

  /**
   * 快照详情
   * GET /api/v1/profile/snapshots/{id}
   */
  getSnapshotDetail: (snapshotId: number): Promise<SnapshotDetail> =>
    request.get<any, SnapshotDetail>(`/profile/snapshots/${snapshotId}`),
}
