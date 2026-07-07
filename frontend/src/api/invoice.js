import { createApiClient } from './request'

const request = createApiClient({ baseURL: '/api/invoice' })

// 后端统一 {code,message,data} 信封，拦截器返回整个信封，这里取业务数据
const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export function searchInvoiceCustomers(params) {
  return unwrap(request.get('/customers/search', { params, showLoading: false }))
}

export function getInvoiceProductOptions(params) {
  return unwrap(request.get('/products/filter-options', { params, showLoading: false }))
}

export function matchInvoiceProduct(params) {
  return unwrap(request.get('/products/match', { params, showLoading: false }))
}

export function getInvoiceEntryOptions() {
  return unwrap(request.get('/products/entry-options', { showLoading: false }))
}

export function listInvoices(params) {
  return unwrap(request.get('/invoices', { params, showLoading: false }))
}

export function getInvoice(id) {
  return unwrap(request.get(`/invoices/${id}`))
}

export function createInvoice(data) {
  return unwrap(request.post('/invoices', data, { loadingText: '正在保存发票...' }))
}

export function updateInvoice(id, data) {
  return unwrap(request.put(`/invoices/${id}`, data, { loadingText: '正在保存发票...' }))
}

export function deleteInvoice(id) {
  return unwrap(request.delete(`/invoices/${id}`, { loadingText: '正在删除发票...' }))
}

export function validateInvoice(id) {
  return unwrap(request.post(`/invoices/${id}/validate`, null, { loadingText: '正在校验发票...' }))
}

export function syncInvoice(id) {
  return unwrap(request.post(`/invoices/${id}/sync`, null, { loadingText: '正在同步小满...' }))
}

// ── 价格 ─────────────────────────────────────────────

export function resolveInvoicePrice(params) {
  return unwrap(request.get('/price/resolve', { params, showLoading: false }))
}

export function listStdPrices(params) {
  return unwrap(request.get('/price/std', { params, showLoading: false }))
}

export function upsertStdPrice(data) {
  return unwrap(request.post('/price/std', data, { loadingText: '正在保存价格...' }))
}

export function deleteStdPrice(id) {
  return unwrap(request.delete(`/price/std/${id}`))
}

export function importPriceWorkbook(formData) {
  return unwrap(request.post('/price/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '正在导入价格表...',
  }))
}

export function listColorTypes() {
  return unwrap(request.get('/price/color-types', { showLoading: false }))
}

export function upsertColorType(data) {
  return unwrap(request.post('/price/color-types', data))
}

export function deleteColorType(id) {
  return unwrap(request.delete(`/price/color-types/${id}`))
}

export function listCustomerRules(params) {
  return unwrap(request.get('/price/customer-rules', { params, showLoading: false }))
}

export function getCustomerRule(customerId) {
  return unwrap(request.get(`/price/customer-rules/by-customer/${customerId}`, { showLoading: false }))
}

export function upsertCustomerRule(data) {
  return unwrap(request.post('/price/customer-rules', data, { loadingText: '正在保存规则...' }))
}

export function deleteCustomerRule(id) {
  return unwrap(request.delete(`/price/customer-rules/${id}`))
}

// ── 自定义产品 ────────────────────────────────────────

export function listCustomProducts(params) {
  return unwrap(request.get('/custom-products', { params, showLoading: false }))
}

export function reconcileCustomProducts() {
  return unwrap(request.post('/custom-products/reconcile', null, { loadingText: '正在对账回填...' }))
}

// ── 导出 ─────────────────────────────────────────────

export function downloadInvoiceExcel(id) {
  return request.get(`/invoices/${id}/export/excel`, {
    responseType: 'blob',
    loadingText: '正在导出 Excel...',
  })
}

export function downloadInvoicePdf(id) {
  return request.get(`/invoices/${id}/export/pdf`, {
    responseType: 'blob',
    loadingText: '正在导出 PDF...',
  })
}

// 打印页在新标签打开不带 Authorization header，必须先鉴权取回 HTML 再本地打开
export function fetchInvoicePrintHtml(id) {
  return request.get(`/invoices/${id}/export/print`, { loadingText: '正在生成打印页...' })
}
