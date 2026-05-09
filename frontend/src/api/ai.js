import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'

const aiApi = axios.create({
  baseURL: '/api/ai',
  timeout: 120000,
})

const loading = useLoading()

aiApi.interceptors.request.use(config => {
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

aiApi.interceptors.response.use(
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
    const msg = error.response?.data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

// Provider
export function getProviders(params) {
  return aiApi.get('/providers', { params, showLoading: false })
}

export function createProvider(data) {
  return aiApi.post('/providers', data, { loadingText: '正在保存...' })
}

export function updateProvider(id, data) {
  return aiApi.put(`/providers/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteProvider(id) {
  return aiApi.delete(`/providers/${id}`)
}

export function testProvider(id) {
  return aiApi.post(`/providers/${id}/test`, {}, { loadingText: '连通性测试中...' })
}

// Preset
export function getPresets(params) {
  return aiApi.get('/presets', { params, showLoading: false })
}

export function createPreset(data) {
  return aiApi.post('/presets', data, { loadingText: '正在保存...' })
}

export function updatePreset(id, data) {
  return aiApi.put(`/presets/${id}`, data, { loadingText: '正在保存...' })
}

export function deletePreset(id) {
  return aiApi.delete(`/presets/${id}`)
}

export function testPreset(id, testMessage) {
  return aiApi.post(`/presets/${id}/test`, { test_message: testMessage }, { loadingText: '测试中...' })
}

// Call Log
export function getLogs(params) {
  return aiApi.get('/logs', { params, showLoading: false })
}

export function getLogDetail(id) {
  return aiApi.get(`/logs/${id}`)
}

// Invoke
export function chat(data) {
  return aiApi.post('/chat', data, { loadingText: 'AI 思考中...' })
}

export function delegate(data) {
  return aiApi.post('/delegate', data, { loadingText: '提交任务中...' })
}

export function getTaskResult(taskId) {
  return aiApi.get(`/tasks/${taskId}`, { showLoading: false })
}

export default aiApi
