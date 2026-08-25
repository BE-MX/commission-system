import { semifinishedClient as api } from './clients'

const data = request => request.then(response => response.data ?? response)

export const getMaterials = params => data(api.get('/materials', { params, showLoading: false }))
export const getMappings = params => data(api.get('/mappings', { params, showLoading: false }))
export const previewMaterialSync = () => data(api.post('/materials/sync-preview', null, { loadingText: '解析产品中...' }))
export const applyMaterialSync = () => data(api.post('/materials/sync-apply', null, { loadingText: '同步半成品中...', timeout: 180000 }))
export const updateMapping = (id, payload) => data(api.put(`/mappings/${id}`, payload, { loadingText: '保存配比中...' }))
export const quoteSemifinished = payload => data(api.post('/quote', payload, { showLoading: false }))

export const getSemifinishedOrders = params => data(api.get('/orders', { params, showLoading: false }))
export const getSemifinishedOrder = id => data(api.get(`/orders/${id}`, { showLoading: false }))
export const createSemifinishedOrder = payload => data(api.post('/orders', payload, { loadingText: '创建半成品订单中...' }))
export const receiveSemifinishedItem = (id, payload) => data(api.post(`/order-items/${id}/receive`, payload, { loadingText: '入库中...' }))
export const terminateSemifinishedOrder = id => data(api.put(`/orders/${id}/status`, { status: 'terminated' }, { loadingText: '终止中...' }))

export const getSemifinishedInventory = params => data(api.get('/inventory', { params, showLoading: false }))
export const getInventoryLedger = (materialId, params) => data(api.get(`/inventory/${materialId}/ledger`, { params, showLoading: false }))
export const adjustSemifinishedInventory = (materialId, payload) => data(api.post(`/inventory/${materialId}/adjust`, payload, { loadingText: '调整库存中...' }))
