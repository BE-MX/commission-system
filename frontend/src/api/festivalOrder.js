import { festivalClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export function getFestivalOrderSummary(params = {}, config = {}) {
  return unwrap(festivalClient.get('/orders/summary', { ...config, params, showLoading: false }))
}

export function listFestivalOrders(params, config = {}) {
  return unwrap(festivalClient.get('/orders', { ...config, params, showLoading: false }))
}
