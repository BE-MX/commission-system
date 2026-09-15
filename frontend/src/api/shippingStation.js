import { shippingClient } from './clients'
const config = { showLoading: false, suppressToast: true, redirectOnUnauthorized: false, timeout: 300000 }
const base = '/station'
export const stationApi = {
  operators: () => shippingClient.get(`${base}/operators`, config),
  scan: body => shippingClient.post(`${base}/scan`, body, config),
  refresh: id => shippingClient.get(`${base}/sessions/${id}`, config),
  upload: (id, type, form, progress) => shippingClient.post(`${base}/sessions/${id}/${type}`, form, { ...config, onUploadProgress: progress }),
  media: (id, media) => shippingClient.get(`${base}/sessions/${id}/media/${media}`, { ...config, responseType: 'blob' }),
  delete: (id, media, params) => shippingClient.delete(`${base}/sessions/${id}/media/${media}`, { ...config, params }),
  submit: (id, body) => shippingClient.post(`${base}/sessions/${id}/submit`, body, config),
  end: id => shippingClient.post(`${base}/sessions/${id}/end`, {}, config),
}
