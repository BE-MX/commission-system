import request from './request'

export function syncPayments(data) {
  return request.post('/payment/sync', data, { loadingText: '正在同步回款...' })
}

export function getSyncedPayments(params) {
  return request.get('/payment/synced/list', { params, showLoading: false })
}
