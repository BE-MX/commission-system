import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'
import { getAccessToken, clearAuthState } from '@/stores/auth'

const sysApi = axios.create({
  baseURL: '/api/system',
  timeout: 30000,
})

const loading = useLoading()

sysApi.interceptors.request.use(config => {
  if (config.showLoading !== false) {
    loading.show(config.loadingText || '')
  }
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

sysApi.interceptors.response.use(
  response => {
    if (response.config.showLoading !== false) loading.hide()
    const res = response.data
    if (res.code !== undefined && res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message))
    }
    return res
  },
  error => {
    if (error.config?.showLoading !== false) loading.hide()
    if (error.response?.status === 401) {
      clearAuthState()
      window.location.href = '/login'
      return Promise.reject(error)
    }
    let msg = error.response?.data?.detail || error.response?.data?.message || error.message || '网络错误'
    if (typeof msg === 'object' && msg !== null) {
      msg = msg.message || JSON.stringify(msg)
    }
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export function getDictTypes() {
  return sysApi.get('/dict-types', { showLoading: false })
}

export function getDictItems(type, onlyActive = false) {
  return sysApi.get('/dicts', { params: { type, only_active: onlyActive }, showLoading: false })
}

export function createDictItem(data) {
  return sysApi.post('/dicts', data, { loadingText: '正在保存...' })
}

export function updateDictItem(id, data) {
  return sysApi.put(`/dicts/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteDictItem(id) {
  return sysApi.delete(`/dicts/${id}`)
}

export default sysApi
