import request from './request'

function noCacheConfig(config = {}) {
  return {
    ...config,
    params: {
      ...(config.params || {}),
      _ts: Date.now(),
    },
    headers: {
      ...(config.headers || {}),
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      Pragma: 'no-cache',
    },
  }
}

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

export function sendConfirmBatch(batchId, data = { notify_dingtalk: true }) {
  return request.post(`/commission/batch/${batchId}/send-confirm`, data, { loadingText: '正在发送确认...' })
}

export function revokeConfirmBatch(batchId) {
  return request.post(`/commission/batch/${batchId}/revoke-confirm`, null, { loadingText: '正在撤销...' })
}

export function getBatchSummary(batchId) {
  return request.get(`/commission/batch/${batchId}/summary`, { showLoading: false })
}

export function getMyCommissionBatches(params) {
  return request.get('/commission/self/batch/list', noCacheConfig({ params, showLoading: false }))
}

export function getMyCommissionBatchDetail(batchId) {
  return request.get(`/commission/self/batch/${batchId}`, noCacheConfig({ showLoading: false }))
}

export function submitMyCommissionFeedback(batchId, data) {
  return request.post(`/commission/self/batch/${batchId}/feedback`, data, { loadingText: '正在提交反馈...' })
}

export function confirmMyCommissionBatch(batchId, data) {
  return request.post(`/commission/self/batch/${batchId}/confirm`, data, { loadingText: '正在提交确认...' })
}

export function exportMyCommissionBatch(batchId) {
  return request.get(`/commission/self/batch/${batchId}/export`, {
    responseType: 'blob',
    loadingText: '正在导出...',
  })
}
