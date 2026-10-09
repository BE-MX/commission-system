import { msgError } from '@/utils/feedback'
/**
 * Auth API — 登录、刷新、获取用户信息
 */
import axios from 'axios'

// 独立的 axios 实例，不走业务 request.js 的拦截器
const authRequest = axios.create({
  baseURL: '/api/auth',
  timeout: 15000,
  withCredentials: true, // 携带 HttpOnly Cookie
})

// 请求拦截器：注入 Access Token
authRequest.interceptors.request.use(async config => {
  const { useAuthStore } = await import('@/stores/auth')
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// 响应错误拦截器：统一处理登录相关错误
authRequest.interceptors.response.use(
  response => response,
  error => {
    if (axios.isCancel(error)) return Promise.reject(error)
    // Kiosk auth recovery needs the original HTTP status and handles its own UI.
    if (error.config?.suppressToast) return Promise.reject(error)
    // 网络层错误（后端未启动、DNS 失败、CORS 等）
    if (!error.response) {
      const msg = error.code === 'ECONNABORTED' || error.code === 'ERR_NETWORK'
        ? '网络超时，请检查后端服务是否启动'
        : '网络错误，请检查网络连接或后端服务'
      msgError(msg)
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    const status = error.response.status
    const data = error.response.data || {}

    // 401 — 用户名或密码错误 / Token 过期
    if (status === 401) {
      const msg = data.detail || data.message || '用户名或密码错误'
      // /refresh 的 401 是匿名访客与会话过期的常态（App.vue 初始化会触达，公开页
      // /inventory 的外部客户也会命中），调用方自有回退逻辑——不弹全局中文 toast
      if (!String(error.config?.url || '').includes('/refresh')) {
        msgError(msg)
      }
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    // 403 — 账号被禁用
    if (status === 403) {
      const msg = data.detail || data.message || '账号已被禁用，请联系管理员'
      msgError(msg)
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    // 423 — 账号被锁定
    if (status === 423) {
      const msg = data.detail || data.message || '账号已锁定，请稍后再试'
      msgError(msg)
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    // 500 — 服务器内部错误
    if (status === 500) {
      const msg = data.detail || data.message || '服务器内部错误，请稍后重试'
      msgError(msg)
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    // 422 — 请求参数校验失败
    if (status === 422) {
      let msg = '请求参数校验失败'
      if (Array.isArray(data.detail) && data.detail.length > 0) {
        msg = data.detail.map(e => e.msg || e.message).filter(Boolean).join('；') || msg
      } else if (typeof data.detail === 'string') {
        msg = data.detail
      }
      msgError(msg)
      error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
    }

    // 其他状态码
    const msg = data.detail || data.message || `请求失败 (${status})`
    msgError(msg)
    error.message = msg
      error._arkFeedbackHandled = true
      return Promise.reject(error)
  }
)

export const authApi = {
  /**
   * 登录
   * @param {{ username: string, password: string }} credentials
   * @returns {Promise<{ access_token, token_type, expires_in, user }>}
   */
  async login(credentials, options = {}) {
    const { data } = await authRequest.post('/login', credentials, options)
    return data
  },

  /**
   * 刷新 Access Token（用 HttpOnly Cookie 中的 refresh_token）
   * @returns {Promise<{ access_token, token_type, expires_in }>}
   */
  async refresh({ suppressToast = false, signal } = {}) {
    const { data } = await authRequest.post('/refresh', null, { suppressToast, signal })
    return data
  },

  /**
   * 获取当前用户信息
   */
  async getMe() {
    const { data } = await authRequest.get('/me')
    return data
  },

  /**
   * 退出登录
   */
  async logout(options = {}) {
    await authRequest.post('/logout', null, options)
  },
}

export { authRequest }
