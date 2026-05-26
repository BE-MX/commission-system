import { stockClient as stockApi } from './clients'

// ── 销量备货一览 ────────────────────────────────────────
export function getStockOverview(params) {
  return stockApi.get('/overview', { params, showLoading: false })
}

// ── 筛选维度可选值(全部产品) ────────────────────────────
export function getFilterOptions() {
  return stockApi.get('/filter-options', { showLoading: false })
}

// ── 安全库存列表 ────────────────────────────────────────
export function getSafetyList(params) {
  return stockApi.get('/safety', { params, showLoading: false })
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
export function getLatestDailyReport() {
  return stockApi.get('/daily-report', { showLoading: false, suppressNotFound: true })
}

export function getDailyReportByDate(date) {
  return stockApi.get(`/daily-report/${date}`, { showLoading: false, suppressNotFound: true })
}

export function triggerDailyReport(params) {
  return stockApi.post('/daily-report/generate', null, { params, loadingText: '生成中...', timeout: 180000 })
}

export function pushDailyReport(params) {
  return stockApi.post('/daily-report/push', null, { params, loadingText: '推送中...', timeout: 60000 })
}

// ── 生产单购物车 ──────────────────────────────────────────
export function getProductionCart() {
  return stockApi.get('/production/cart', { showLoading: false })
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
export function queryInTransit(productIds) {
  return stockApi.post('/production/in-transit', { product_ids: productIds }, { showLoading: false })
}

// ── 备货状态 ──────────────────────────────────────────────
export function queryStockStatus(productIds) {
  return stockApi.post('/production/stock-status', { product_ids: productIds }, { showLoading: false })
}

// ── 生产订单 ──────────────────────────────────────────────
export function createProductionOrder(payload) {
  return stockApi.post('/production/orders', payload, { loadingText: '创建订单中...' })
}

export function getProductionOrders(params) {
  return stockApi.get('/production/orders', { params, showLoading: false })
}

export function getProductionOrderDetail(orderId) {
  return stockApi.get(`/production/orders/${orderId}`, { showLoading: false })
}

export function updateProductionOrder(orderId, payload) {
  return stockApi.put(`/production/orders/${orderId}`, payload, { loadingText: '更新中...' })
}

export function deleteProductionOrder(orderId) {
  return stockApi.delete(`/production/orders/${orderId}`, { loadingText: '删除中...' })
}

export function getProductionOrderItems(params) {
  return stockApi.get('/production/order-items', { params, showLoading: false })
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
