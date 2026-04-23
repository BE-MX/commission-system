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
    const msg = error.response?.data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default service
