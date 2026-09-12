import request from './request'

export interface LoginParams {
  username: string
  password: string
}

export interface RegisterParams {
  username: string
  password: string
  email?: string
  phone?: string
}

export interface UserInfo {
  id: number
  username: string
  email: string | null
  phone: string | null
  role: string
  status: number
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export const authApi = {
  login: (data: LoginParams) =>
    request.post<any, TokenResponse>('/auth/login', data),

  register: (data: RegisterParams) =>
    request.post<any, UserInfo>('/auth/register', data),

  getMe: () =>
    request.get<any, UserInfo>('/auth/me'),
}
