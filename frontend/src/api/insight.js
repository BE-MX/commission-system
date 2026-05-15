import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'
import { getAccessToken, clearAuthState } from '@/stores/auth'

const insightApi = axios.create({
  baseURL: '/api/insight',
  timeout: 90000,
})

const loading = useLoading()

insightApi.interceptors.request.use((config) => {
  if (config.showLoading !== false) {
    loading.show(config.loadingText || '')
  }
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

insightApi.interceptors.response.use(
  (response) => {
    if (response.config.showLoading !== false) loading.hide()
    const res = response.data
    if (res && res.code !== undefined && res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message))
    }
    return res
  },
  (error) => {
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

// ── 报告 ──────────────────────────────────────────────
export function listReports(params) {
  return insightApi.get('/reports', { params, showLoading: false })
}

export function getReport(id) {
  return insightApi.get(`/reports/${id}`, { showLoading: false })
}

export function getReportHtmlUrl(id) {
  // iframe src 直接绑定该 URL
  return `/api/insight/reports/${id}/html`
}

export function getReportHtml(id) {
  return insightApi.get(`/reports/${id}/html`, { showLoading: false, responseType: 'text' })
}

export function regenerateReport(id) {
  return insightApi.post(`/reports/${id}/regenerate`, null, { loadingText: '正在重新生成...' })
}

export function triggerReportGeneration(reportType) {
  return insightApi.post(`/reports/generate/${reportType}`, null, { loadingText: '正在生成报告...' })
}

// ── 信源 ──────────────────────────────────────────────
export function listSources(params) {
  return insightApi.get('/sources', { params, showLoading: false })
}

export function getSource(id) {
  return insightApi.get(`/sources/${id}`, { showLoading: false })
}

export function createSource(data) {
  return insightApi.post('/sources', data, { loadingText: '正在保存...' })
}

export function updateSource(id, data) {
  return insightApi.put(`/sources/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteSource(id) {
  return insightApi.delete(`/sources/${id}`, { loadingText: '正在禁用...' })
}

export function testSource(id) {
  return insightApi.post(`/sources/${id}/test`, null, { loadingText: '正在测试连通性...' })
}

// ── 案例库 ────────────────────────────────────────────
export function listCases(params) {
  return insightApi.get('/cases', { params, showLoading: false })
}

export function getCaseDetail(id) {
  return insightApi.get(`/cases/${id}`, { showLoading: false })
}

export function getCaseStatus(id) {
  return insightApi.get(`/cases/${id}/status`, { showLoading: false })
}

export function uploadCase(formData) {
  return insightApi.post('/cases/upload', formData, {
    loadingText: 'AI 处理中,请稍候...',
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function manualCreateCase(data) {
  return insightApi.post('/cases/manual', data, { loadingText: '正在发布...' })
}

export function publishCase(id, data) {
  return insightApi.post(`/cases/${id}/publish`, data, { loadingText: '正在发布...' })
}

export function updateCase(id, data) {
  return insightApi.put(`/cases/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteCase(id) {
  return insightApi.delete(`/cases/${id}`, { loadingText: '正在删除...' })
}

export function toggleCaseLike(id, delta = 1) {
  return insightApi.post(`/cases/${id}/like`, null, {
    params: { delta },
    showLoading: false,
  })
}

// ── 周会纪要 ────────────────────────────────────────────
export function uploadMinutes(data) {
  return insightApi.post('/minutes/upload', data, { loadingText: 'AI 处理中,请稍候...' })
}

export function listMinutes(params) {
  return insightApi.get('/minutes', { params, showLoading: false })
}

export function getMinutesDetail(id) {
  return insightApi.get(`/minutes/${id}`, { showLoading: false })
}

export function updateTask(taskId, data) {
  return insightApi.patch(`/tasks/${taskId}`, data, { showLoading: false })
}

export function exportTasksCsvUrl(minutesId) {
  return `/api/insight/minutes/${minutesId}/tasks/export`
}

// ── 工作台摘要 ──────────────────────────────────────────
export function getDashboardSummary() {
  return insightApi.get('/dashboard/summary', { showLoading: false })
}

export default insightApi
