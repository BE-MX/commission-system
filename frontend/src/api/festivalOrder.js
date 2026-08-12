import { festivalClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export function getFestivalOrderSummary(params = {}) {
  return unwrap(festivalClient.get('/orders/summary', { params, showLoading: false }))
}

export function listFestivalOrders(params) {
  return unwrap(festivalClient.get('/orders', { params, showLoading: false }))
}
