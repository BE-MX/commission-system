import { commerceShadowClient as api } from './clients'
export const getShadowStatus = (config = {}) => api.get('/status', config)
export const getShadowRuns = (params, config = {}) => api.get('/runs', { ...config, params })
export const getShadowRun = (id, config = {}) => api.get(`/runs/${id}`, config)
export const exportShadowInput = (id, config = {}) => api.get(`/runs/${id}/input`, config)
export const importShadowReceipts = (id, body, config = {}) => api.post(`/runs/${id}/receipts`, body, config)
export const queueShadowRun = body => api.post('/runs', body)
export const getShadowDifferences = (params, config = {}) => api.get('/differences', { ...config, params })
export const reviewShadowDifference = (id, body) => api.post(`/differences/${id}/review`, body)
