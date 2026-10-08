import { domesticDecisionClient as client } from './clients'

const quiet = { showLoading: false, suppressToast: true }
const get = (url, params) => client.get(url, { ...quiet, params }).then(res => res.data)
const post = (url, body) => client.post(url, body, quiet).then(res => res.data)
export const domesticDecisionApi = {
  filters: () => get('/filters'),
  analyze: query => post('/analysis-runs', query),
  rows: (id, params) => get(`/analysis-runs/${encodeURIComponent(id)}/rows`, params),
  evidence: (kind, id) => get(`/evidence/${encodeURIComponent(kind)}/${id}`),
  customer: (id, params) => get(`/customers/${id}/profile`, params),
  salesperson: (id, params) => get(`/salespeople/${id}/profile`, params),
  views: () => get('/views'),
  saveView: body => post('/views', body),
  updateView: (id, body) => client.patch(`/views/${id}`, body, quiet).then(res => res.data),
  deleteView: id => client.delete(`/views/${id}`, quiet).then(res => res.data),
  actions: () => get('/actions'),
  createAction: body => post('/actions', body),
  updateAction: (id, body) => client.patch(`/actions/${id}`, body, quiet).then(res => res.data),
  createJob: (kind, body) => post(`/${kind}`, body),
  job: (kind, id) => get(`/${kind}/${encodeURIComponent(id)}`),
  briefs: () => get('/briefs'),
  download: id => client.get(`/exports/${encodeURIComponent(id)}/download`, { ...quiet, responseType: 'blob' }),
  settings: () => get('/settings'),
  mapping: body => post('/mappings', body),
  config: (key, body) => client.put(`/settings/${encodeURIComponent(key)}`, body, quiet).then(res => res.data),
}
