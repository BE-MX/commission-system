import { domesticFollowupClient as client } from './clients'

// 页面自己给反馈（utils/feedback），不走全局 loading / toast
const quiet = { showLoading: false, suppressToast: true }
const data = res => res.data
const get = (url, params) => client.get(url, { ...quiet, params }).then(data)
const post = (url, body) => client.post(url, body, quiet).then(data)

export const followupApi = {
  config: () => get('/config'),
  saveConfig: body => client.put('/config', body, quiet).then(data),
  dicts: () => get('/dicts'),
  users: q => get('/users', { q }),
  searchCustomers: q => get('/customers/search', { q }),
  createProspect: shopName => post('/customers/prospect', { shop_name: shopName }),
  timeline: customerId => get(`/customers/${customerId}/timeline`),
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
  followups: params => get('/followups', params),
  createDraft: body => post('/drafts', body),
  drafts: () => get('/drafts'),
  draft: id => get(`/drafts/${id}`),
  confirmDraft: (id, body) => post(`/drafts/${id}/confirm`, body),
  discardDraft: id => client.delete(`/drafts/${id}`, quiet).then(data),
  tasks: params => get('/tasks', params),
  summary: () => get('/tasks/summary'),
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
