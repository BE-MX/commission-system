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

export const authApi = {
  /**
   * 登录
   * @param {{ username: string, password: string }} credentials
   * @returns {Promise<{ access_token, token_type, expires_in, user }>}
   */
  async login(credentials) {
    const { data } = await authRequest.post('/login', credentials)
    return data
  },

  /**
   * 刷新 Access Token（用 HttpOnly Cookie 中的 refresh_token）
   * @returns {Promise<{ access_token, token_type, expires_in }>}
   */
  async refresh() {
    const { data } = await authRequest.post('/refresh')
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
  async logout() {
    await authRequest.post('/logout')
  },
}

export { authRequest }
