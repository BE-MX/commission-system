import { colorClient } from './clients'

// ── 色号 CRUD ───────────────────────────────────────────
export function getColors(params) {
  return colorClient.get('/colors', { params, showLoading: false })
}

export function getColorDetail(id) {
  return colorClient.get(`/colors/${id}`, { showLoading: false })
}

export function createColor(data) {
  return colorClient.post('/colors', data, { loadingText: '创建中...' })
}

export function updateColor(id, data) {
  return colorClient.put(`/colors/${id}`, data, { loadingText: '保存中...' })
}

export function deleteColor(id) {
  return colorClient.delete(`/colors/${id}`)
}

export function getColorFilterOptions() {
  return colorClient.get('/colors/filter-options', { showLoading: false })
}

// ── 混合色 CRUD ─────────────────────────────────────────
export function getBlends(params) {
  return colorClient.get('/blends', { params, showLoading: false })
}

export function getBlendDetail(id) {
  return colorClient.get(`/blends/${id}`, { showLoading: false })
}

export function createBlend(data) {
  return colorClient.post('/blends', data, { loadingText: '创建中...' })
}

export function updateBlend(id, data) {
  return colorClient.put(`/blends/${id}`, data, { loadingText: '保存中...' })
}

export function deleteBlend(id) {
  return colorClient.delete(`/blends/${id}`)
}

export function getBlendFilterOptions() {
  return colorClient.get('/blends/filter-options', { showLoading: false })
}

// ── 色彩计算 ────────────────────────────────────────────
export function colorCalcConvert(data) {
  return colorClient.post('/color-calc/convert', data, { showLoading: false })
}

export function colorCalcBlend(data) {
  return colorClient.post('/color-calc/blend', data, { showLoading: false })
}

export function colorCalcDeltaE(data) {
  return colorClient.post('/color-calc/delta-e', data, { showLoading: false })
}

export function colorCalcPantoneMatch(data) {
  return colorClient.post('/color-calc/pantone-match', data, { showLoading: false })
}

export function colorCalcMatchLeshine(data) {
  return colorClient.post('/color-calc/match-leshine', data, { showLoading: false })
}

export function colorExtractFromImage(file, k = 5) {
  const formData = new FormData()
  formData.append('file', file)
  return colorClient.post('/color-calc/extract-from-image', formData, {
    params: { k },
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '分析中...',
    timeout: 30000,
  })
}

// ── 色板图生成 ──────────────────────────────────────────
export function generateSwatch(data) {
  return colorClient.post('/swatch/generate', data, { loadingText: '任务创建中...' })
}

export function getSwatchStatus(taskId) {
  return colorClient.get(`/swatch/${taskId}/status`, { showLoading: false })
}

export function batchGenerateSwatch(data) {
  return colorClient.post('/swatch/batch-generate', data, { loadingText: '批量创建中...' })
}

export function verifySwatch(taskId) {
  return colorClient.post(`/swatch/${taskId}/verify`, {}, { loadingText: '校验中...' })
}

export function getSwatches(params) {
  return colorClient.get('/swatches', { params, showLoading: false })
}

// ── 趋势数据 ────────────────────────────────────────────
export function getTrendOverview() {
  return colorClient.get('/color-trends/overview', { showLoading: false })
}

export function getTrendHistory(params) {
  return colorClient.get('/color-trends/history', { params, showLoading: false })
}

export function getTrendPrediction(params) {
  return colorClient.get('/color-trends/prediction', { params, showLoading: false })
}

export function getSocialColors() {
  return colorClient.get('/color-trends/social-colors', { showLoading: false })
}
