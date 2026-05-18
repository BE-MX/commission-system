import { stockClient as stockApi } from './clients'

// ── 销量备货一览 ────────────────────────────────────────
export function getStockOverview(params) {
  return stockApi.get('/overview', { params, showLoading: false })
}

// ── 筛选维度可选值(全部产品) ────────────────────────────
export function getFilterOptions() {
  return stockApi.get('/filter-options', { showLoading: false })
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
