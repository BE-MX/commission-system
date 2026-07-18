import { createApiClient } from './request'

const request = createApiClient({ baseURL: '/api/invoice' })

// 后端统一 {code,message,data} 信封，拦截器返回整个信封，这里取业务数据
const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export function searchInvoiceCustomers(params) {
  return unwrap(request.get('/customers/search', { params, showLoading: false }))
}

// 联系人维度搜客户（与公司筛选联动）；private_only=仅私海
export function searchInvoiceCustomerContacts(params) {
  return unwrap(request.get('/customers/contacts', { params, showLoading: false }))
}

export function suggestInvoiceNo(params) {
  return unwrap(request.get('/invoices/suggest-no', { params, showLoading: false }))
}

export function checkInvoiceNo(params) {
  return unwrap(request.get('/invoices/check-no', { params, showLoading: false }))
}

export function getCustomerContactDefaults(customerId) {
  return unwrap(request.get('/customers/contact-defaults', {
    params: { customer_id: customerId }, showLoading: false,
  }))
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

export function previewInvoiceImport(data) {
  return unwrap(request.post('/import/preview', data, {
    loadingText: '正在校验导入明细...',
  }))
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

export function getInvoiceSyncLogs(id) {
  return unwrap(request.get(`/invoices/${id}/sync-logs`, { showLoading: false }))
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

export function searchAccessoryCandidates(params) {
  return unwrap(request.get('/price/accessory-candidates', { params, showLoading: false }))
}

export function listAccessoryPrices(params) {
  return unwrap(request.get('/price/accessories', { params, showLoading: false }))
}

export function saveAccessoryPrice(data) {
  return unwrap(request.post('/price/accessories', data, { loadingText: '正在保存配件价格...' }))
}

export function deleteAccessoryPrice(id) {
  return unwrap(request.delete(`/price/accessories/${id}`))
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

// ── OKKI 推单设置 ─────────────────────────────────────

export function getXiaomanSettings() {
  return unwrap(request.get('/xiaoman/settings', { showLoading: false }))
}

export function updateXiaomanSettings(data) {
  return unwrap(request.put('/xiaoman/settings', data, { loadingText: '正在保存设置...' }))
}

export function resolveXiaomanProduct(params) {
  return unwrap(request.get('/xiaoman/settings/resolve-product', { params, showLoading: false }))
}

export function fetchXiaomanToken() {
  return unwrap(request.post('/xiaoman/settings/fetch-token', null, { loadingText: '正在向 OKKI 获取 Token...' }))
}

export function getXiaomanEnums() {
  return unwrap(request.get('/xiaoman/enums', { showLoading: false }))
}

// ── 回款日期修复 ──────────────────────────────────────

export function previewReceiptRepair(formData) {
  return unwrap(request.post('/receipt-repair/preview', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '正在匹配工作表...',
  }))
}

export function applyReceiptRepair(data) {
  return unwrap(request.post('/receipt-repair/apply', data, { loadingText: '正在写入修复...' }))
}

export function exportReceiptRepairUnmatched(data) {
  return request.post('/receipt-repair/export-unmatched', data, {
    responseType: 'blob',
    loadingText: '正在导出无法匹配清单...',
  })
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
