import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'
import { getAccessToken, clearAuthState } from '@/stores/auth'

const loading = useLoading()

/**
 * 创建一个共享拦截器配置的 axios client。
 *
 * 拦截器统一处理:
 *   - loading: 通过 config.showLoading (默认 true) 与 config.loadingText 控制
 *   - 注入 Bearer Token: 从 @/stores/auth.getAccessToken() 同步读取
 *   - 401: 清除认证状态并跳转 /login
 *   - 404 + config.suppressNotFound: 静默 reject (调用方自处理)
 *   - blob response: 直接返回完整 response (调用方可拿 headers + blob)
 *   - 业务码: response.data.code !== 200/201 时弹错误
 *
 * @param {{ baseURL: string, timeout?: number }} options
 * @returns {import('axios').AxiosInstance}
 */
export function createApiClient({ baseURL, timeout = 60000 } = {}) {
  const service = axios.create({ baseURL, timeout })

  service.interceptors.request.use(config => {
    if (config.showLoading !== false) {
      loading.show(config.loadingText || '')
    }
    const token = getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  service.interceptors.response.use(
    response => {
      if (response.config.showLoading !== false) {
        loading.hide()
      }
      if (response.config.responseType === 'blob') {
        return response
      }
      const res = response.data
      // 业务码校验: text response (string) 跳过, JSON 才进入此分支
      if (res && typeof res === 'object' && res.code !== undefined
          && res.code !== 200 && res.code !== 201) {
        ElMessage.error(res.message || '请求失败')
        return Promise.reject(new Error(res.message || '请求失败'))
      }
      return res
    },
    error => {
      if (error.config?.showLoading !== false) {
        loading.hide()
      }
      // 调用方主动 suppress 404 (例如"暂无日报"页)
      if (error.response?.status === 404 && error.config?.suppressNotFound) {
        return Promise.reject(error)
      }
      if (error.response?.status === 401) {
        clearAuthState()
        window.location.href = '/login'
        return Promise.reject(error)
      }
      let msg = error.response?.data?.detail || error.response?.data?.message
        || error.message || '网络错误'
      if (typeof msg === 'object' && msg !== null) {
        msg = msg.message || JSON.stringify(msg)
      }
      ElMessage.error(msg)
      return Promise.reject(error)
    }
  )

  return service
}

// 默认 client: /api/v1 (向后兼容,旧代码 `import service from '@/api/request'` 不需改)
const v1Client = createApiClient({ baseURL: '/api/v1' })
export default v1Client
