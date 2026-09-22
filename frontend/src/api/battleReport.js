import { battleReportClient as client } from './clients'

const unwrap = promise => promise.then(res => res?.data ?? res)
const options = params => ({ params, showLoading: false })
export const battleReportApi = {
  list: params => unwrap(client.get('', options(params))),
  participants: () => unwrap(client.get('/participants', options())),
  create: payload => unwrap(client.post('', payload)),
  get: id => unwrap(client.get(`/${id}`, options())),
  update: (id, payload) => unwrap(client.put(`/${id}`, payload)),
  state: (id, payload) => unwrap(client.post(`/${id}/state`, payload)),
  targets: (id, payload) => unwrap(client.put(`/${id}/targets`, payload)),
  overview: (id, params) => unwrap(client.get(`/${id}/overview`, options(params))),
  daily: (id, params) => unwrap(client.get(`/${id}/daily`, options(params))),
  orders: (id, params) => unwrap(client.get(`/${id}/orders`, options(params))),
  order: (id, orderId) => unwrap(client.get(`/${id}/orders/${encodeURIComponent(orderId)}`, options())),
  audits: (id, params) => unwrap(client.get(`/${id}/audits`, options(params))),
}
