import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { ADMIN_NAME_KEY, ADMIN_TOKEN_KEY } from '@/stores/auth'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(ADMIN_TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)

    // 登录接口自身的 401/403 只提示、不跳转（否则整页刷新会把提示冲掉）
    const isLoginRequest = String(error.config?.url ?? '').includes('/admin/auth/login')
    if (error.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem(ADMIN_TOKEN_KEY)
      localStorage.removeItem(ADMIN_NAME_KEY)
      window.location.href = `${import.meta.env.BASE_URL}login`
    }

    return Promise.reject(error)
  },
)

// Wrapper with proper typing
export function get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request.get(url, config) as Promise<T>
}

export function post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request.post(url, data, config) as Promise<T>
}

export function put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request.put(url, data, config) as Promise<T>
}

export function del<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request.delete(url, config) as Promise<T>
}

// Alias for del
export { del as remove }

export default request
