import request from './request'

export function syncPayments(data) {
  return request.post('/payment/sync', data)
}

export function getSyncedPayments(params) {
  return request.get('/payment/synced/list', { params })
}
