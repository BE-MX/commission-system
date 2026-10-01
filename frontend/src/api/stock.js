import { stockClient as stockApi, publicStockClient } from './clients'

// ── 对外库存查询（无登录，全公开；客户查询页 /inventory 用） ──
export function getPublicInventory(params, config = {}) {
  return publicStockClient.get('/products', { showLoading: false, suppressToast: true, ...config, params })
}

// ── 销量备货一览 ────────────────────────────────────────
export function getStockOverview(params, config = {}) {
  return stockApi.get('/overview', { showLoading: false, ...config, params })
}

// ── 筛选维度可选值(全部产品) ────────────────────────────
export function getFilterOptions(config = {}) {
  return stockApi.get('/filter-options', { showLoading: false, ...config })
}

// ── 安全库存列表 ────────────────────────────────────────
export function getSafetyList(params, config = {}) {
  return stockApi.get('/safety', { showLoading: false, ...config, params })
}

// ── 批量保存安全库存 ────────────────────────────────────
export function saveSafetyStock(payload) {
  return stockApi.post('/safety', payload, { loadingText: '保存中...' })
}

// ── AI 批量生成建议 ─────────────────────────────────────
export function autoGenerateSafety(payload) {
  return stockApi.post('/safety/auto-generate', payload, { loadingText: 'AI 生成中...', timeout: 120000 })
}

// ── TFT 预测(单 SKU) ───────────────────────────────────
export function tftPredict(payload) {
  return stockApi.post('/tft-predict', payload, { loadingText: 'AI 预测中...' })
}

// ── 日报 ────────────────────────────────────────────────
export function getLatestDailyReport(config = {}) {
  return stockApi.get('/daily-report', { showLoading: false, suppressNotFound: true, ...config })
}

export function getDailyReportByDate(date, config = {}) {
  return stockApi.get(`/daily-report/${date}`, { showLoading: false, suppressNotFound: true, ...config })
}

export function triggerDailyReport(params) {
  return stockApi.post('/daily-report/generate', null, { params, loadingText: '生成中...', timeout: 180000 })
}

export function pushDailyReport(params) {
  return stockApi.post('/daily-report/push', null, { params, loadingText: '推送中...', timeout: 60000 })
}

// ── 生产单购物车 ──────────────────────────────────────────
export function getProductionCart(config = {}) {
  return stockApi.get('/production/cart', { showLoading: false, ...config })
}

export function addToProductionCart(payload) {
  return stockApi.post('/production/cart', payload, { loadingText: '添加中...' })
}

export function updateProductionCartItem(cartId, payload) {
  return stockApi.put(`/production/cart/${cartId}`, payload, { loadingText: '更新中...' })
}

export function deleteProductionCartItem(cartId) {
  return stockApi.delete(`/production/cart/${cartId}`, { loadingText: '删除中...' })
}

export function deleteProductionCartItems(cartIds) {
  const params = new URLSearchParams()
  cartIds.forEach(id => params.append('cart_ids', id))
  return stockApi.delete(`/production/cart?${params.toString()}`, { loadingText: '删除中...' })
}

// ── 生产在途 ──────────────────────────────────────────────
export function queryInTransit(productIds, config = {}) {
  return stockApi.post('/production/in-transit', { product_ids: productIds }, { showLoading: false, ...config })
}

// ── 备货状态 ──────────────────────────────────────────────
export function queryStockStatus(productIds, config = {}) {
  return stockApi.post('/production/stock-status', { product_ids: productIds }, { showLoading: false, ...config })
}

// ── 生产订单 ──────────────────────────────────────────────
export function createProductionOrder(payload) {
  return stockApi.post('/production/orders', payload, { loadingText: '创建订单中...' })
}

export function getProductionOrders(params, config = {}) {
  return stockApi.get('/production/orders', { showLoading: false, ...config, params })
}

export function getProductionOrderDetail(orderId, config = {}) {
  return stockApi.get(`/production/orders/${orderId}`, { showLoading: false, ...config })
}

export function updateProductionOrder(orderId, payload) {
  return stockApi.put(`/production/orders/${orderId}`, payload, { loadingText: '更新中...' })
}

export function deleteProductionOrder(orderId) {
  return stockApi.delete(`/production/orders/${orderId}`, { loadingText: '删除中...' })
}

export function getProductionOrderItems(params, config = {}) {
  return stockApi.get('/production/order-items', { showLoading: false, ...config, params })
}

export function updateProductionOrderItem(itemId, payload) {
  return stockApi.put(`/production/order-items/${itemId}`, payload, { loadingText: '更新中...' })
}

export function updateProductionItemStatus(itemId, payload) {
  return stockApi.put(`/production/order-items/${itemId}/status`, payload, { loadingText: '更新中...' })
}

export function updateProductionItemReceived(itemId, payload) {
  return stockApi.put(`/production/order-items/${itemId}/received`, payload, { loadingText: '更新中...' })
}

export function deleteProductionOrderItem(itemId) {
  return stockApi.delete(`/production/order-items/${itemId}`, { loadingText: '删除中...' })
}

export function resetOrderProcess(orderId) {
  return stockApi.post(`/production/orders/${orderId}/reset-process`, null, { loadingText: '重置工艺中...' })
}

// ── 生产订单打印工作台 ────────────────────────────────────────

export function getProductionPrintOrders(params, config = {}) {
  return stockApi.get('/production/print-orders', { showLoading: false, ...config, params })
}

export function getOrderPrintCategories(orderId, config = {}) {
  return stockApi.get(`/production/orders/${orderId}/print-categories`, { showLoading: false, ...config })
}

export function createProductionPrintJob(orderId, payload) {
  return stockApi.post(`/production/orders/${orderId}/print-jobs`, payload, { loadingText: '打印中...' })
}
