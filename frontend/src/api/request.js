import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'

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
  try {
    const { useAuthStore } = require('@/stores/auth')
    const auth = useAuthStore()
    if (auth.accessToken) {
      config.headers.Authorization = `Bearer ${auth.accessToken}`
    }
  } catch (e) {
    // store 未初始化时忽略
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
    if (res.code !== undefined && res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res
  },
  error => {
    if (error.config?.showLoading !== false) {
      loading.hide()
    }
    // 401 时跳转登录页
    if (error.response?.status === 401) {
      try {
        const { useAuthStore } = require('@/stores/auth')
        const auth = useAuthStore()
        auth.logout()
      } catch (e) {
        // ignore
      }
      return Promise.reject(error)
    }
    const msg = error.response?.data?.detail || error.response?.data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default service
