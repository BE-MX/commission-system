/**
 * 生产报工 API client
 */
import { createApiClient } from './request'

const productionClient = createApiClient({ baseURL: '/api/production', timeout: 60000 })

// ── 工序管理 ──────────────────────────────────────────
export const getProcesses = (params) => productionClient.get('/processes', { params })
export const createProcess = (data) => productionClient.post('/processes', data)
export const updateProcess = (id, data) => productionClient.put(`/processes/${id}`, data)
export const deleteProcess = (id) => productionClient.delete(`/processes/${id}`)
export const getActiveProcesses = () => productionClient.get('/active-processes')

// ── 工序路线管理 ──────────────────────────────────────
export const getProcessRoutes = (params) => productionClient.get('/process-routes', { params })
export const createProcessRoute = (data) => productionClient.post('/process-routes', data)
export const updateProcessRoute = (id, data) => productionClient.put(`/process-routes/${id}`, data)
export const deleteProcessRoute = (id) => productionClient.delete(`/process-routes/${id}`)
export const getRouteSteps = (id) => productionClient.get(`/process-routes/${id}/steps`)
export const saveRouteSteps = (id, steps) => productionClient.post(`/process-routes/${id}/steps`, { steps })
export const getActiveRoutes = () => productionClient.get('/active-routes')

// ── 产品管理 + 路线绑定 ──────────────────────────────
export const getProducts = (params) => productionClient.get('/products', { params })
export const getProductFilterOptions = () => productionClient.get('/products/filter-options')
export const getProductRoute = (productId) => productionClient.get(`/products/${productId}/process-route`)
export const bindProductRoute = (productId, data) => productionClient.post(`/products/${productId}/process-route`, data)
export const batchBindRoute = (data) => productionClient.post('/products/batch-bind-route', data)

// ── 用户工序绑定 + 微信ID ─────────────────────────────
export const getUserProcessBindings = (userId) => productionClient.get(`/users/${userId}/process-bindings`)
export const updateUserProcessBindings = (userId, processIds) =>
  productionClient.put(`/users/${userId}/process-bindings`, { process_ids: processIds })
export const updateUserWxId = (userId, wxId) =>
  productionClient.put(`/users/${userId}/wx-id`, { wx_id: wxId })

// ── 进度 ─────────────────────────────────────────────
export const initProgress = (orderProductId, force = false) =>
  productionClient.post(`/order-products/${orderProductId}/init-progress`, { force })
export const getProgress = (orderProductId) =>
  productionClient.get(`/order-products/${orderProductId}/progress`)

// ── 二维码 / 打印卡 ─────────────────────────────────
export const getQRCode = (orderProductId, size = 200) =>
  productionClient.get(`/order-products/${orderProductId}/qrcode`, { params: { size } })
export const getPrintCardData = (orderProductId) =>
  productionClient.get(`/order-products/${orderProductId}/print-card`)

// ── 生产看板 ──────────────────────────────────────────
export const getDashboardData = () => productionClient.get('/dashboard')
