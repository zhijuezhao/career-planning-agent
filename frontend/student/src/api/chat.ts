/**
 * 聊天 API 模块
 * 封装会话管理、消息发送（SSE流式）等接口 */

import request from './request'

// ==================== 类型定义 ====================

/** 聊天会话 */
export interface ChatSession {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

/** 聊天消息 */
export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

/** 会话列表响应 */
export interface ChatSessionListResponse {
  total: number
  items: ChatSession[]
}

/** 会话详情（含消息历史） */
export interface ChatSessionDetail {
  id: string
  title: string | null
  messages: ChatMessage[]
  created_at: string
  updated_at: string
}

/** 创建会话请求 */
export interface ChatSessionCreateReq {
  title?: string
}

/** 发送消息请求 */
export interface ChatSendReq {
  content: string
}

/** SSE 流式回调集合 */
export interface ChatStreamCallbacks {
  onToken: (text: string) => void
  onDone: (data: { session_id: string; message_id: number }) => void
  onError: (error: string) => void
  /** 模型调用工具的进度（后端 agent 发 `tool` 事件时才有；老后端不发则不会触发） */
  onTool?: (info: { phase: 'start' | 'end'; name: string }) => void
}

// ==================== API 方法 ====================

/**
 * 创建新会话
 */
export function createSession(data: ChatSessionCreateReq) {
  return request.post<any, ChatSession>('/chat/sessions', data)
}

/**
 * 获取当前用户的会话列表
 */
export function listSessions(params?: { skip?: number; limit?: number }) {
  return request.get<any, ChatSessionListResponse>('/chat/sessions', { params })
}

/**
 * 获取会话详情（含消息历史）
 */
export function getSessionDetail(sessionId: string) {
  return request.get<any, ChatSessionDetail>(`/chat/sessions/${sessionId}`)
}

/**
 * 删除会话
 */
export function deleteSession(sessionId: string) {
  return request.delete(`/chat/sessions/${sessionId}`)
}

/**
 * 发送消息（SSE流式响应）
 * 使用 fetch API 原生支持流式读取
 * @param sessionId 会话ID
 * @param content 消息内容
 * @param onToken 接收到token时的回调
 * @param onDone 流式完成时的回调
 * @param onError 错误回调
 * @returns AbortController 用于取消请求
 */
export function sendMessage(
  sessionId: string,
  content: string,
  callbacks: ChatStreamCallbacks
): AbortController {
  const controller = new AbortController()
  const token = localStorage.getItem('access_token')

  // 异步执行SSE流式读取
  ;(async () => {
    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/chat/sessions/${sessionId}/messages`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        }
      )

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        callbacks.onError(errorData.detail || `请求失败 (${response.status})`)
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError('无法读取响应流')
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按行解析SSE事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 最后一行可能不完整，保留到下次

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const eventData = JSON.parse(line.slice(6))
              handleSSEEvent(eventData, callbacks)
            } catch {
              // 忽略解析失败的行
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return // 用户主动取消
      callbacks.onError(err.message || '网络错误')
    }
  })()

  return controller
}

/**
 * 解析SSE事件数据
 */
function handleSSEEvent(data: any, callbacks: ChatStreamCallbacks) {
  switch (data.type) {
    case 'token':
      callbacks.onToken(data.content)
      break
    case 'tool':
      // 模型正在/刚调用完某个工具（phase: start | end）
      callbacks.onTool?.({ phase: data.phase, name: data.name })
      break
    case 'done':
      callbacks.onDone({ session_id: data.session_id, message_id: data.message_id })
      break
    case 'error':
      callbacks.onError(data.content)
      break
  }
}
