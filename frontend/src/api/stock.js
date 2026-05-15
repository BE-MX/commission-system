import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useLoading } from '@/composables/useLoading'
import { getAccessToken, clearAuthState } from '@/stores/auth'

const stockApi = axios.create({
  baseURL: '/api/stock',
  timeout: 90000,
})

const loading = useLoading()

stockApi.interceptors.request.use((config) => {
  if (config.showLoading !== false) {
    loading.show(config.loadingText || '')
  }
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

stockApi.interceptors.response.use(
  (response) => {
    if (response.config.showLoading !== false) loading.hide()
    const res = response.data
    if (res && res.code !== undefined && res.code !== 200 && res.code !== 201) {
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
    // 404 在日报页面里需要由调用方决定如何处理(显示"暂无日报"),不弹全局 toast
    if (error.response?.status === 404 && error.config?.suppressNotFound) {
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

// ── 销量备货一览 ────────────────────────────────────────
export function getStockOverview(params) {
  return stockApi.get('/overview', { params, showLoading: false })
}

// ── 安全库存列表 ────────────────────────────────────────
export function getSafetyList(params) {
  return stockApi.get('/safety', { params, showLoading: false })
}

// ── 批量保存安全库存 ────────────────────────────────────
export function saveSafetyStock(payload) {
  return stockApi.post('/safety', payload, { loadingText: '保存中...' })
}

// ── AI 批量生成建议 ─────────────────────────────────────
export function autoGenerateSafety(payload) {
  return stockApi.post('/safety/auto-generate', payload, { loadingText: 'AI 生成中...', timeout: 120000 })
}

// ── TFT 预测(单 SKU) ───────────────────────────────────
export function tftPredict(payload) {
  return stockApi.post('/tft-predict', payload, { loadingText: 'AI 预测中...' })
}

// ── 日报 ────────────────────────────────────────────────
export function getLatestDailyReport() {
  return stockApi.get('/daily-report', { showLoading: false, suppressNotFound: true })
}

export function getDailyReportByDate(date) {
  return stockApi.get(`/daily-report/${date}`, { showLoading: false, suppressNotFound: true })
}

export function triggerDailyReport(params) {
  return stockApi.post('/daily-report/generate', null, { params, loadingText: '生成中...', timeout: 180000 })
}
