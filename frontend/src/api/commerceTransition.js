import { commerceTransitionClient as api } from './clients'
export const getTransitionStatus = (config = {}) => api.get('/status', config)
export const getInvoiceAuthority = (id, config = {}) => api.get(`/invoices/${id}/authority`, config)
export const setInvoiceRoute = (id, body) => api.post(`/invoices/${id}/route`, body)
export const getTransitionResource = (resource, config = {}) => api.get(`/${resource}`, config)
export const saveTransitionResource = (resource, body) => api.post(`/${resource}`, body)
