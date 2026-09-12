import request from './request'

export interface ResumeStatus {
  resume_id: number
  status: string
  error_message: string | null
  profile_id: number | null
  created_at: string
  updated_at: string
}

export interface ResumeDetail {
  resume_id: number
  file_name: string
  status: string
  page_count: number | null
  parsed_data: Record<string, any>
  profile_id: number | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface ReportData {
  report_id: number
  profile_id: number
  target_job: string | null
  report_content: Record<string, any> | null
  version: number
  created_at: string
}

export interface RadarOption {
  indicators: { name: string; max: number }[]
  values: number[]
  total_score: number
}

export const resumeApi = {
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post<any, { resume_id: number; status: string }>(
      '/resume/upload',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  },

  getLatest: () =>
    request.get<any, ResumeStatus>('/resume/latest'),

  getDetail: (resumeId: number) =>
    request.get<any, ResumeDetail>(`/resume/${resumeId}`),

  getReport: (resumeId: number) =>
    request.get<any, ReportData>(`/resume/${resumeId}/report`),

  getRadar: (resumeId: number) =>
    request.get<any, RadarOption>(`/resume/${resumeId}/radar`),
}
