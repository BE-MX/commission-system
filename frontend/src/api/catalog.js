import { catalogClient as api } from './clients'
export const getProducts = (params, config = {}) => api.get('/products', { ...config, params })
export const createProduct = body => api.post('/products', body)
export const updateProduct = (id, body) => api.put(`/products/${id}`, body)
export const createSku = (id, body) => api.post(`/products/${id}/skus`, body)
export const setSkuStatus = (id, active) => api.put(`/skus/${id}/status`, { active })
export const updateSku = (id, body) => api.put(`/skus/${id}`, body)
