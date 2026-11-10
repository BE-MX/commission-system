import { alibabaFeedClient } from './clients'
const options = { showLoading: false, suppressToast: true }
const unwrap = promise => promise.then(response => response.data)
const path = value => encodeURIComponent(value)
export const alibabaFeedApi = {
  records: (params, signal) => unwrap(alibabaFeedClient.get('/business/records', { ...options, params, signal })),
  record: (id, signal) => unwrap(alibabaFeedClient.get(`/business/records/${path(id)}`, { ...options, signal })),
  customers: (params, signal) => unwrap(alibabaFeedClient.get('/business/customers', { ...options, params, signal })),
  customerRecords: (id, signal) => unwrap(alibabaFeedClient.get(`/business/customers/${path(id)}/records`, { ...options, signal })),
  link: data => unwrap(alibabaFeedClient.post('/business/links', data, options)),
  unlink: (id, expectedVersion) => unwrap(alibabaFeedClient.delete(`/business/links/${path(id)}`, { ...options, params: { expected_version: expectedVersion } })),
  pilot: signal => unwrap(alibabaFeedClient.get('/pilot', { ...options, signal })),
  savePilot: data => unwrap(alibabaFeedClient.put('/pilot', data, options)),
  activatePilot: data => unwrap(alibabaFeedClient.post('/pilot/activation', data, options)),
}
