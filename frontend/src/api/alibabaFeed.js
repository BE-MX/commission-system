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
  sources: signal => unwrap(alibabaFeedClient.get('/sources', { ...options, signal })),
  owners: signal => unwrap(alibabaFeedClient.get('/owners', { ...options, signal })),
  saveSource: (id, data) => unwrap(alibabaFeedClient.patch(`/sources/${path(id)}`, data, options)),
}
