import { aiChatClient } from './clients'
import { getAccessToken, clearAuthState } from '@/stores/auth'
import { consumeSseStream } from '@/views/design/ai-chat/state'

const API_BASE = '/api/ai-chat'

export const getConfig = () => aiChatClient.get('/config')
export const createSession = (data = {}) => aiChatClient.post('/sessions', data)
export const listSessions = (params = {}) => aiChatClient.get('/sessions', { params })
export const getSession = sessionId => aiChatClient.get(`/sessions/${sessionId}`)

export function uploadAttachment(sessionId, file) {
  const form = new FormData()
  form.append('file', file)
  return aiChatClient.post(`/sessions/${sessionId}/attachments`, form)
}

export const deleteAttachment = attachmentId => (
  aiChatClient.delete(`/attachments/${attachmentId}`)
)

export const getAttachmentContent = attachmentId => (
  aiChatClient.get(`/attachments/${attachmentId}/content`, {
    responseType: 'blob',
    showLoading: false,
  })
)

function redirectToLogin() {
  clearAuthState()
  if (typeof window !== 'undefined') window.location.href = '/login'
}

async function responseError(response) {
  let detail = ''
  try {
    const payload = await response.json()
    detail = payload?.detail || payload?.message || ''
  } catch {
    detail = ''
  }
  if (detail && typeof detail === 'object') {
    detail = detail.message || JSON.stringify(detail)
  }
  const error = new Error(detail || `请求失败 (${response.status})`)
  error.status = response.status
  error.detail = detail
  return error
}

async function streamRequest(path, body, { signal, onEvent } = {}) {
  const token = getAccessToken()
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) redirectToLogin()
    throw await responseError(response)
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.toLowerCase().includes('text/event-stream')) {
    throw new Error('服务器未返回流式响应，请稍后重试')
  }
  if (!response.body) {
    throw new Error('浏览器无法读取流式响应')
  }

  return consumeSseStream(response.body, { onEvent })
}

export async function streamTurn(sessionId, body, options) {
  return streamRequest(`/sessions/${sessionId}/turns/stream`, body, options)
}

export async function streamRetry(messageId, body, options) {
  return streamRequest(`/messages/${messageId}/retry/stream`, body, options)
}
