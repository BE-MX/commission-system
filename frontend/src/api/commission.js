import request from './request'

export function createBatch(data) {
  return request.post('/commission/batch', data, { loadingText: '正在创建...' })
}

export function getBatchList(params) {
  return request.get('/commission/batch/list', { params, showLoading: false })
}

export function calculateBatch(batchId) {
  return request.post(`/commission/batch/${batchId}/calculate`, null, {
    timeout: 300000,
    loadingText: '正在计算提成，请稍候...',
  })
}

export function getBatchDetails(batchId, params) {
  return request.get(`/commission/batch/${batchId}/details`, { params, showLoading: false })
}

export function confirmBatch(batchId, data) {
  return request.post(`/commission/batch/${batchId}/confirm`, data, { loadingText: '正在确认...' })
}

export function voidBatch(batchId) {
  return request.post(`/commission/batch/${batchId}/void`, null, { loadingText: '正在作废...' })
}

export function getBatchSummary(batchId) {
  return request.get(`/commission/batch/${batchId}/summary`, { showLoading: false })
}
