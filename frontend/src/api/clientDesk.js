import { clientDeskClient, clientDeskPublicClient } from './clients'
const options = { showLoading: false, suppressToast: true }
const unwrap = promise => promise.then(response => response.data)
export const clientDeskApi = {
  waOpen: (id, data) => unwrap(clientDeskClient.post(`/customers/${encodeURIComponent(id)}/wa-open`, data, options)),
  sampleDate: date => unwrap(clientDeskClient.get('/calendar/sample-followup', { ...options, params: { date } })),
  today: params => unwrap(clientDeskClient.get('/today', { ...options, params })),
  customers: params => unwrap(clientDeskClient.get('/customers', { ...options, params })),
  customer: (id, signal) => unwrap(clientDeskClient.get(`/customers/${encodeURIComponent(id)}`, { ...options, signal })),
  freshCustomer: id => unwrap(clientDeskClient.get(`/customers/${encodeURIComponent(id)}`, { ...options, params: { fresh: true } })),
  timeline: (id, params, signal) => unwrap(clientDeskClient.get(`/customers/${encodeURIComponent(id)}/timeline`, { ...options, params, signal })),
  evidence: (id, key, signal) => unwrap(clientDeskClient.get(`/customers/${encodeURIComponent(id)}/timeline/events/${encodeURIComponent(key)}`, { ...options, signal })),
  state: (id, data) => unwrap(clientDeskClient.patch(`/customers/${encodeURIComponent(id)}/state`, data, options)),
  grade: (id, data) => unwrap(clientDeskClient.put(`/customers/${encodeURIComponent(id)}/grade`, data, options)),
  followup: (id, data) => unwrap(clientDeskClient.post(`/customers/${encodeURIComponent(id)}/followups`, data, options)),
  reanalyze: (id, data) => unwrap(clientDeskClient.post(`/customers/${encodeURIComponent(id)}/reanalyze`, data, options)),
  feedback: (id, data) => unwrap(clientDeskClient.post(`/suggestions/${encodeURIComponent(id)}/feedback`, data, options)),
  conversations: params => unwrap(clientDeskClient.get('/unlinked-conversations', { ...options, params })),
  link: data => unwrap(clientDeskClient.post('/wa-links', data, options)),
  unlink: id => unwrap(clientDeskClient.delete(`/wa-links/${encodeURIComponent(id)}`, options)),
  handoff: () => unwrap(clientDeskPublicClient.get('/reports/handoff', options)),
  redeem: ticket => unwrap(clientDeskPublicClient.post('/reports/redeem', { ticket }, options)),
}
