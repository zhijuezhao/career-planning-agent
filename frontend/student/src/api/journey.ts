/**
 * 旅程状态 API 模块
 * 封装后端旅程状态查询，作为守卫/布局定位阶段真相的来源
 * 对应后端 API: GET /api/v1/journey/status
 */

import request from './request'

export type JourneyStage =
  | 'start'
  | 'upload'
  | 'parsing'
  | 'jobs'
  | 'matching'
  | 'career'
  | 'report'
  | 'done'

export interface JourneyStatusResponse {
  stage: JourneyStage
  resume_id?: number | null
  profile_id?: number | null
  match_id?: number | null
  path_id?: number | null
  plan_id?: number | null
  report_id?: number | null
}

export const journeyApi = {
  getStatus: (): Promise<JourneyStatusResponse> =>
    request.get<any, JourneyStatusResponse>('/journey/status'),
}