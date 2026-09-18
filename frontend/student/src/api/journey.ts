/**
 * 旅程状态 API 模块
 * 封装后端旅程状态查询，作为守卫/布局定位阶段真相的来源
 * 对应后端 API: GET /api/v1/journey/status
 */

import request from './request'

export type Zone = 'welcome' | 'guide' | 'business'
export type GuideStep = 'resume' | 'parse' | 'match' | 'career' | 'done'

export interface JourneyStatusResponse {
  zone: Zone
  guide_step: GuideStep | null
  snapshot_id: number | null
  report_id: number | null
  report_versions: number
}

export const journeyApi = {
  getStatus: () => request.get<any, JourneyStatusResponse>('/journey/status'),
}