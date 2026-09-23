/**
 * 模型配置中心 API（B2-1）
 *
 * 后端：`app/api/v1/admin/system.py` 的 `/system/providers|models|routes|models/{id}/test`
 * 约定：api_key 只回掩码（`sk-***1234`），明文永不出后端；任何写操作后端会立即重建
 * 注册表快照并失效网关/向量单例 —— 所以前端保存后无需重启或额外刷新即可生效。
 */
import { get, post, put, remove } from '@/api/request'

export interface LLMProvider {
  id: number
  name: string
  base_url: string | null
  enabled: boolean
  sort_order: number
  api_key_set: boolean
  api_key_masked: string
  model_count: number
  created_at: string
  updated_at: string
}

export interface LLMModel {
  id: number
  provider_id: number
  provider_name: string | null
  model_name: string
  display_name: string | null
  kind: 'chat' | 'embedding'
  dim: number | null
  temperature: number | null
  max_tokens: number | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface FunctionRoute {
  function_key: string
  label: string
  kind: 'chat' | 'embedding'
  bound_model_id: number | null
  bound_model: string | null
  source: 'db' | 'env'
  effective: string
  fallback: string
  warning: string | null
  updated_at: string | null
}

export interface ConnectivityResult {
  ok: boolean
  model: string
  kind: string
  latency_ms: number
  dim: number | null
  dim_expected: number | null
  output_preview: string | null
  detail: string
}

export interface ProviderPayload {
  name?: string
  base_url?: string | null
  api_key?: string | null
  enabled?: boolean
  sort_order?: number
}

export interface ModelPayload {
  provider_id?: number
  model_name?: string
  display_name?: string | null
  kind?: 'chat' | 'embedding'
  dim?: number | null
  temperature?: number | null
  max_tokens?: number | null
  enabled?: boolean
}

const BASE = '/v1/admin/system'

export const listProviders = () => get<{ total: number; items: LLMProvider[] }>(`${BASE}/providers`)

export const createProvider = (payload: ProviderPayload) =>
  post<LLMProvider>(`${BASE}/providers`, payload)

export const updateProvider = (id: number, payload: ProviderPayload) =>
  put<LLMProvider>(`${BASE}/providers/${id}`, payload)

export const deleteProvider = (id: number) => remove(`${BASE}/providers/${id}`)

export const listModels = (params?: { provider_id?: number; kind?: string }) =>
  get<{ total: number; items: LLMModel[] }>(`${BASE}/models`, { params })

export const createModel = (payload: ModelPayload) => post<LLMModel>(`${BASE}/models`, payload)

export const updateModel = (id: number, payload: ModelPayload) =>
  put<LLMModel>(`${BASE}/models/${id}`, payload)

export const deleteModel = (id: number) => remove(`${BASE}/models/${id}`)

export const testModel = (id: number) => post<ConnectivityResult>(`${BASE}/models/${id}/test`)

export const listRoutes = () => get<{ total: number; items: FunctionRoute[] }>(`${BASE}/routes`)

/** model_id 传 null = 解绑（回到 env/default 行为） */
export const bindRoute = (functionKey: string, modelId: number | null) =>
  put<FunctionRoute>(`${BASE}/routes/${functionKey}`, { model_id: modelId })

export const getSchedulerStatus = () =>
  get<{ status: string; jobs: Array<Record<string, unknown>> }>(`${BASE}/scheduler/status`)
