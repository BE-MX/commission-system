// 内贸订单 API（响应拦截器已解包信封，调用方取数用 res.data）
import { domesticClient } from './clients'

// 与后端 constants.py 同一套口径
export const PRODUCT_TYPE_LABELS = { cap: '头套', piece: '发片' }
export const ORDER_TYPE_LABELS = { normal: '普货', special: '特单' }
export const ORDER_STATUS = [
  { value: 0, label: '草稿', tag: 'warning' },
  { value: 1, label: '生产中', tag: '' },
  { value: 2, label: '已完工', tag: 'success' },
  { value: 3, label: '已发货', tag: 'info' },
  { value: 4, label: '已终止', tag: 'danger' },
]
export const ORDER_STATUS_LABELS = Object.fromEntries(ORDER_STATUS.map(s => [s.value, s.label]))
export const ORDER_STATUS_TAGS = Object.fromEntries(ORDER_STATUS.map(s => [s.value, s.tag]))
export const ITEM_STATUS_LABELS = { 0: '生产中', 1: '已完工', 2: '已发货' }

// 明细图文四区：文字字段 + 对应图片字段，下单表单与详情抽屉共用这份定义
export const DETAIL_SECTIONS = [
  { key: 'hairstyle', imageKey: 'hairstyle_images', label: '发型', placeholder: '如：马姐旗袍直发' },
  { key: 'color', imageKey: 'color_images', label: '颜色', placeholder: '如：自然色' },
  { key: 'style_requirement', imageKey: 'style_images', label: '发型要求', placeholder: '如：精致到位，直接试戴直接卖' },
  { key: 'remark', imageKey: 'remark_images', label: '备注', placeholder: '如：鬓角宽一点' },
]

// ── 值域与路线 ──
export function getOptions() {
  return domesticClient.get('/options')
}

export function getProcessRoutes() {
  return domesticClient.get('/process-routes')
}

export function listProcessWorkers(processId) {
  return domesticClient.get('/process-workers', { params: { process_id: processId } })
}

// 报工幂等键：提交失败重试时复用同一个值，服务端不会重复累加数量
export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

// ── 客户 ──
export function listCustomers(params) {
  return domesticClient.get('/customers', { params })
}

export function createCustomer(data) {
  return domesticClient.post('/customers', data)
}

export function updateCustomer(id, data) {
  return domesticClient.put(`/customers/${id}`, data)
}

export function deleteCustomer(id) {
  return domesticClient.delete(`/customers/${id}`)
}

export function rechargeCustomer(id, data) {
  return domesticClient.post(`/customers/${id}/recharges`, data)
}

export function listCustomerBalanceLedger(id, params) {
  return domesticClient.get(`/customers/${id}/balance-ledger`, { params })
}

// ── 产品与工艺映射 ──
export function listProducts(params) {
  return domesticClient.get('/products', { params })
}

export function rebindProductRoute(productId, routeId) {
  return domesticClient.put(`/products/${productId}/route`, { route_id: routeId })
}

export function listCraftRoutes() {
  return domesticClient.get('/craft-routes')
}

export function upsertCraftRoute(data) {
  return domesticClient.post('/craft-routes', data)
}

export function deleteCraftRoute(id) {
  return domesticClient.delete(`/craft-routes/${id}`)
}

// ── 订单 ──
export function createOrder(data) {
  return domesticClient.post('/orders', data)
}

export function listOrders(params) {
  return domesticClient.get('/orders', { params })
}

export function getOrder(id) {
  return domesticClient.get(`/orders/${id}`)
}

export function updateOrder(id, data) {
  return domesticClient.put(`/orders/${id}`, data)
}

export function submitDraftOrder(id) {
  return domesticClient.post(`/orders/${id}/submit`)
}

export function terminateOrder(id, reason) {
  return domesticClient.post(`/orders/${id}/status`, { status: 4, reason })
}

export function deleteOrder(id) {
  return domesticClient.delete(`/orders/${id}`)
}

// 订单进度小程序码：从任一明细生成，微信扫码免登录看完整订单
export function getItemWxacode(itemId) {
  return domesticClient.get(`/items/${itemId}/wxacode`)
}

// ── 明细 ──
export function attachItemRoute(itemId, routeId) {
  return domesticClient.post(`/items/${itemId}/attach-route`, { route_id: routeId })
}

export function shipItem(itemId, data) {
  return domesticClient.post(`/items/${itemId}/ship`, data)
}

export function getPrintCard(itemId) {
  return domesticClient.get(`/items/${itemId}/print-card`)
}

export function getItemUnitQrcodes(itemId, params) {
  return domesticClient.get(`/items/${itemId}/unit-qrcodes`, { params })
}

// ── 报工 ──
export function listReports(params) {
  return domesticClient.get('/reports', { params })
}

export function submitReport(data) {
  return domesticClient.post('/reports', data)
}

export function revokeReport(logId) {
  return domesticClient.post('/reports/revoke', { log_id: logId })
}

// ── 参考图 ──
export function uploadImage(file) {
  const form = new FormData()
  form.append('file', file)
  return domesticClient.post('/images', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}

// 图片走鉴权端点，浏览器 <img src> 不带 token —— 一律取 blob 再转 object URL
// （同 aftersales 证据图的做法，见 memory feedback_iframe-auth-vhtml）
export async function fetchImageBlobUrl(path) {
  const res = await domesticClient.get(`/images/${path}`, { responseType: 'blob' })
  return URL.createObjectURL(res.data)
}

// 打印文档要塞进 iframe，blob URL 在跨文档场景不可靠，一律转 data URL
export async function fetchImageDataUrl(path) {
  const res = await domesticClient.get(`/images/${path}`, { responseType: 'blob' })
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(res.data)
  })
}
