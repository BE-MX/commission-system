import { domesticFollowupClient as client } from './clients'

// 页面自己给反馈（utils/feedback），不走全局 loading / toast
const quiet = { showLoading: false, suppressToast: true }
const data = res => res.data
const get = (url, params, options) => client.get(url, { ...quiet, ...options, params }).then(data)
const post = (url, body) => client.post(url, body, quiet).then(data)

export const followupApi = {
  config: () => get('/config'),
  saveConfig: body => client.put('/config', body, quiet).then(data),
  dicts: () => get('/dicts'),
  users: q => get('/users', { q }),
  searchCustomers: q => get('/customers/search', { q }),
  createProspect: body => post('/customers/prospect', typeof body === 'string' ? { shop_name: body } : body),
  timeline: (customerId, params, options) => get(`/customers/${customerId}/timeline`, params, options),
  customerOverview: (params, options) => get('/customer-overview', params, options),
  customerSummary: (id, options) => get(`/customers/${id}/overview`, undefined, options),
  updateCustomerContact: (id, body) => client.put(`/customers/${id}/contact`, body, quiet).then(data),
  updateCustomerDeal: (id, body) => client.put(`/customers/${id}/deal-status`, body, quiet).then(data),
  collaboration: (id, options) => get(`/collaboration/${id}`, undefined, options),
  collaborationAction: (id, body) => post(`/collaboration/${id}/actions`, body),
  collaborationCandidates: id => get(`/collaboration/${id}/candidates`),
  collaborationTasks: (id, action) => get(`/collaboration/${id}/tasks`, { action }),
  collaborationEvents: (id, params, options) => get(`/collaboration/${id}/events`, params, options),
  collaborationScopes: (params, options) => get('/collaboration/settings/scopes', params, options),
  collaborationUsers: q => get('/collaboration/settings/users', { q }),
  collaborationThresholds: () => get('/collaboration/settings/thresholds'),
  saveCollaborationThresholds: body => client.put('/collaboration/settings/thresholds', body, quiet).then(data),
  addCollaborationScope: body => post('/collaboration/settings/scopes', body),
  removeCollaborationScope: id => client.delete(`/collaboration/settings/scopes/${id}`, quiet).then(data),
  collaborationInitialization: (params, options) => get('/collaboration/initialize', params, options),
  initializeCollaboration: items => post('/collaboration/initialize', { items }),
  collaborationCoordination: (params, options) => get('/collaboration/coordination', params, options),
  upload(file) {
    const form = new FormData()
    form.append('file', file)
    return client.post('/attachments', form, { ...quiet, headers: { 'Content-Type': 'multipart/form-data' } }).then(data)
  },
  // 截图走鉴权端点，<img src> 不带 token：取 blob 转 object URL（memory feedback_iframe-auth-vhtml）
  async attachmentUrl(id) {
    const res = await client.get(`/attachments/${id}/file`, { ...quiet, responseType: 'blob' })
    return URL.createObjectURL(res.data)
  },
  directSave: body => post('/followups', body),
  followups: (params, options) => get('/followups', params, options),
  followupAuthors: (params, options) => get('/followups/authors', params, options),
  followup: id => get(`/followups/${id}`),
  editFollowup: (id, body) => client.put(`/followups/${id}`, body, quiet).then(data),
  followupHistory: id => get(`/followups/${id}/history`),
  createDraft: body => post('/drafts', body),
  drafts: params => get('/drafts', params),
  draft: id => get(`/drafts/${id}`),
  confirmDraft: (id, body) => post(`/drafts/${id}/confirm`, body),
  discardDraft: id => client.delete(`/drafts/${id}`, quiet).then(data),
  tasks: params => get('/tasks', params),
  summary: params => get('/tasks/summary', params),
  snooze: (id, days) => post(`/tasks/${id}/snooze`, { days }),
  receiptOk: (id, requestId) => post(`/tasks/${id}/receipt-ok`, { request_id: requestId }),
  items: params => get('/items', params),
  resolveItem: (id, body) => post(`/items/${id}/resolve`, body),
  transferItem: (id, body) => post(`/items/${id}/transfer`, body),
}

// request.js 的响应拦截器已经把 axios 响应换成 {code,message,data} 信封，这里再取一层 .data，
// 调用方拿到的就是业务数据本身，不要再写 (await followupApi.x()).data（同 domesticDecision.js 用法）
export function apiError(error, fallback = '操作失败') {
  return error?.response?.data?.detail || error?.response?.data?.message || fallback
}
