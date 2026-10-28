import { colorClient } from './clients'

// 色板库（公库 / 私库）+ 色差仪测量；后端前缀 /api/color/library
const base = '/library'

export function getLibraryCustomers(params) {
  return colorClient.get(`${base}/customers`, { params, showLoading: false })
}

export function getLibrarySwatches(params) {
  return colorClient.get(`${base}/swatches`, { params, showLoading: false })
}

export function getLibrarySwatch(id) {
  return colorClient.get(`${base}/swatches/${id}`, { showLoading: false })
}

export function createLibrarySwatch(data) {
  return colorClient.post(`${base}/swatches`, data)
}

export function updateLibrarySwatch(id, data) {
  return colorClient.patch(`${base}/swatches/${id}`, data)
}

export function archiveLibrarySwatch(id) {
  return colorClient.delete(`${base}/swatches/${id}`)
}

// 测量批量写入带 client_request_id 幂等键；不显示全局 loading，避免打断连续测量
export function addSwatchMeasurements(id, items) {
  return colorClient.post(`${base}/swatches/${id}/measurements`, { items }, { showLoading: false })
}

export function setMeasurementInclusion(id, measurementId, data) {
  return colorClient.patch(`${base}/swatches/${id}/measurements/${measurementId}`, data)
}

export function requestSwatchPromotion(id) {
  return colorClient.post(`${base}/swatches/${id}/promote`)
}

export function getSwatchPromotions() {
  return colorClient.get(`${base}/promotions`, { showLoading: false })
}

export function reviewSwatchPromotion(id, approve) {
  return colorClient.post(`${base}/swatches/${id}/promotion-review`, { approve })
}
