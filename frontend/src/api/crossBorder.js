import { crossBorderClient as client } from './clients'
const cleanFilters = params => Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value != null))
const quiet = { showLoading: false, suppressToast: true }
export const crossBorderApi = {
  list: (params, config) => client.get('/declarations', { ...quiet, ...config, params: cleanFilters(params) }),
  detail: hash => client.get(`/declarations/${encodeURIComponent(hash)}`, quiet),
  imports: () => client.get('/imports', quiet),
  upload(file, onProgress) {
    const data = new FormData()
    data.append('files', file)
    return client.post('/imports', data, { ...quiet, onUploadProgress: e => onProgress?.(e.total ? Math.round(e.loaded / e.total * 100) : 0) })
  },
  review: (hash, data) => client.post(`/declarations/${encodeURIComponent(hash)}/reviews`, data, quiet),
  export: data => client.post('/exports', data, quiet),
  file: (id, kind) => client.get(`/exports/${id}/files/${kind}`, { ...quiet, responseType: 'blob' }),
}
