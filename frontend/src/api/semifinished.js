import { semifinishedClient as api } from './clients'

const data = request => request.then(response => response.data ?? response)

export const getMaterials = (params, config = {}) => data(api.get('/materials', { showLoading: false, ...config, params }))
export const getMappings = (params, config = {}) => data(api.get('/mappings', { showLoading: false, ...config, params }))
export const previewMaterialSync = (config = {}) => data(api.post('/materials/sync-preview', null, { loadingText: '解析产品中...', ...config }))
export const applyMaterialSync = () => data(api.post('/materials/sync-apply', null, { loadingText: '同步半成品中...', timeout: 180000 }))
export const updateMapping = (id, payload) => data(api.put(`/mappings/${id}`, payload, { loadingText: '保存配比中...' }))
export const quoteSemifinished = (payload, config = {}) => data(api.post('/quote', payload, { showLoading: false, ...config }))

export const getSemifinishedOrders = (params, config = {}) => data(api.get('/orders', { showLoading: false, ...config, params }))
export const getSemifinishedOrder = (id, config = {}) => data(api.get(`/orders/${id}`, { showLoading: false, ...config }))
export const createSemifinishedOrder = payload => data(api.post('/orders', payload, { loadingText: '创建半成品订单中...' }))
export const receiveSemifinishedItem = (id, payload) => data(api.post(`/order-items/${id}/receive`, payload, { loadingText: '入库中...' }))
export const terminateSemifinishedOrder = id => data(api.put(`/orders/${id}/status`, { status: 'terminated' }, { loadingText: '终止中...' }))

export const getSemifinishedInventory = (params, config = {}) => data(api.get('/inventory', { showLoading: false, ...config, params }))
export const getInventoryLedger = (materialId, params, config = {}) => data(api.get(`/inventory/${materialId}/ledger`, { showLoading: false, ...config, params }))
export const adjustSemifinishedInventory = (materialId, payload) => data(api.post(`/inventory/${materialId}/adjust`, payload, { loadingText: '调整库存中...' }))
