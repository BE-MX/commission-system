/**
 * 生产报工 API client
 */
import { productionClient } from './clients'

// ── 工序管理 ──────────────────────────────────────────
export const getProcesses = (params, config = {}) => productionClient.get('/processes', { ...config, params })
export const createProcess = (data) => productionClient.post('/processes', data)
export const updateProcess = (id, data) => productionClient.put(`/processes/${id}`, data)
export const deleteProcess = (id) => productionClient.delete(`/processes/${id}`)
export const getActiveProcesses = (config = {}) => productionClient.get('/active-processes', { ...config, showLoading: false })

// ── 工序路线管理 ──────────────────────────────────────
export const getProcessRoutes = (params, config = {}) => productionClient.get('/process-routes', { ...config, params })
export const createProcessRoute = (data) => productionClient.post('/process-routes', data)
export const updateProcessRoute = (id, data) => productionClient.put(`/process-routes/${id}`, data)
export const deleteProcessRoute = (id) => productionClient.delete(`/process-routes/${id}`, { suppressToast: true })
export const getRouteSteps = (id, config = {}) => productionClient.get(`/process-routes/${id}/steps`, { ...config, showLoading: false })
export const saveRouteSteps = (id, steps) => productionClient.post(`/process-routes/${id}/steps`, { steps })
export const getActiveRoutes = (config = {}) => productionClient.get('/active-routes', { ...config, showLoading: false })

// ── 产品管理 + 路线绑定 ──────────────────────────────
export const getProducts = (params, config = {}) => productionClient.get('/products', { ...config, params })
export const getProductFilterOptions = (config = {}) => productionClient.get('/products/filter-options', { ...config, showLoading: false })
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
export const getProgress = (orderProductId, config = {}) =>
  productionClient.get(`/order-products/${orderProductId}/progress`, config)

// ── 二维码 / 打印卡 ─────────────────────────────────
export const getQRCode = (orderProductId, size = 200) =>
  productionClient.get(`/order-products/${orderProductId}/qrcode`, { params: { size } })
export const getPrintCardData = (orderProductId, config = {}) =>
  productionClient.get(`/order-products/${orderProductId}/print-card`, config)

// ── 生产看板 ──────────────────────────────────────────
export const getDashboardData = (config = {}) => productionClient.get('/dashboard', { ...config, showLoading: false })
