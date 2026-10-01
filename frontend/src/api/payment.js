import request from './request'

export function syncPayments(data) {
  return request.post('/payment/sync', data, { loadingText: '正在同步回款...' })
}

export function getSyncedPayments(params, config = {}) {
  return request.get('/payment/synced/list', { ...config, params, showLoading: false })
}
