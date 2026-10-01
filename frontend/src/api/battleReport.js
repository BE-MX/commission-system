import { battleReportClient as client } from './clients'

const unwrap = promise => promise.then(res => res?.data ?? res)
const options = params => ({ params, showLoading: false })
export const battleReportApi = {
  list: (params, config = {}) => unwrap(client.get('', { ...config, ...options(params) })),
  participants: (config = {}) => unwrap(client.get('/participants', { ...config, ...options() })),
  create: payload => unwrap(client.post('', payload)),
  get: (id, config = {}) => unwrap(client.get(`/${id}`, { ...config, ...options() })),
  update: (id, payload) => unwrap(client.put(`/${id}`, payload)),
  state: (id, payload) => unwrap(client.post(`/${id}/state`, payload)),
  targets: (id, payload) => unwrap(client.put(`/${id}/targets`, payload)),
  overview: (id, params, config = {}) => unwrap(client.get(`/${id}/overview`, { ...config, ...options(params) })),
  daily: (id, params) => unwrap(client.get(`/${id}/daily`, options(params))),
  orders: (id, params, config = {}) => unwrap(client.get(`/${id}/orders`, { ...config, ...options(params) })),
  order: (id, orderId) => unwrap(client.get(`/${id}/orders/${encodeURIComponent(orderId)}`, options())),
  audits: (id, params, config = {}) => unwrap(client.get(`/${id}/audits`, { ...config, ...options(params) })),
  posterConfig: id => unwrap(client.get(`/${id}/poster-config`, options())),
  savePosterConfig: (id, payload) => unwrap(client.put(`/${id}/poster-config`, payload)),
  previewPosters: id => unwrap(client.post(`/${id}/posters/preview`, {}, { timeout: 120000, showLoading: false })),
}
