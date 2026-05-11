import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'
import { getAccessToken, clearAuthState } from '@/stores/auth'

const service = axios.create({
  baseURL: '/api/v1',
  timeout: 60000
})

const loading = useLoading()

service.interceptors.request.use(config => {
  if (config.showLoading !== false) {
    loading.show(config.loadingText || '')
  }
  // 注入 Access Token
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
    if (res.code !== undefined && res.code !== 200 && res.code !== 201) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res
  },
  error => {
    if (error.config?.showLoading !== false) {
      loading.hide()
    }
    // 401 时清除认证状态并跳转登录页
    if (error.response?.status === 401) {
      clearAuthState()
      window.location.href = '/login'
      return Promise.reject(error)
    }
    let msg = error.response?.data?.detail || error.response?.data?.message || error.message || '网络错误'
    // FastAPI HTTPException detail 可能是对象，提取其中的 message
    if (typeof msg === 'object' && msg !== null) {
      msg = msg.message || JSON.stringify(msg)
    }
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default service
