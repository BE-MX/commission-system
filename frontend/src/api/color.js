import { colorClient } from './clients'

// ── 色号 CRUD ───────────────────────────────────────────
export function getColors(params, config = {}) {
  return colorClient.get('/colors', { ...config, params, showLoading: false })
}

// Selectors need the full catalog; the backend accepts at most 200 rows per page.
export async function getAllColorsForSelection(config = {}) {
  const items = new Map()
  let total = 0
  for (let page = 1; page === 1 || (page - 1) * 200 < total; page++) {
    config.signal?.throwIfAborted()
    const response = await getColors({ page, page_size: 200 }, config)
    const result = response.data
    const rows = result?.items || []
    if (page === 1) total = result?.total ?? rows.length
    if (!rows.length && (page - 1) * 200 < total) throw new Error('色号选项未完整读取，请重试')
    for (const row of rows) items.set(row.id, row)
  }
  if (items.size < total) throw new Error('色号选项未完整读取，请重试')
  return [...items.values()]
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

export function getColorFilterOptions(config = {}) {
  return colorClient.get('/colors/filter-options', { ...config, showLoading: false })
}

// ── 混合色 CRUD ─────────────────────────────────────────
export function getBlends(params, config = {}) {
  return colorClient.get('/blends', { ...config, params, showLoading: false })
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

export function getBlendFilterOptions(config = {}) {
  return colorClient.get('/blends/filter-options', { ...config, showLoading: false })
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

export function getSwatches(params, config = {}) {
  return colorClient.get('/swatches', { ...config, params, showLoading: false })
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
