import { inventoryClient as api } from './clients'
export const getWarehouses = (config = {}) => api.get('/warehouses', config)
export const createWarehouse = body => api.post('/warehouses', body)
export const getBalances = (params, config = {}) => api.get('/balances', { ...config, params })
export const getLedger = (params, config = {}) => api.get('/ledger', { ...config, params })
export const getDocuments = (params, config = {}) => api.get('/documents', { ...config, params })
export const getDocument = (id, config = {}) => api.get(`/documents/${id}`, config)
export const postDocument = body => api.post('/documents', body)
export const reverseDocument = (id, body) => api.post(`/documents/${id}/reversal`, body)
