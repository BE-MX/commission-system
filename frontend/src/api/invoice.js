import { createApiClient } from './request'

const request = createApiClient({ baseURL: '/api/invoice' })

export function searchInvoiceCustomers(params) {
  return request.get('/customers/search', { params, showLoading: false })
}

export function getInvoiceProductOptions(params) {
  return request.get('/products/filter-options', { params, showLoading: false })
}

export function matchInvoiceProduct(params) {
  return request.get('/products/match', { params, showLoading: false })
}

export function listInvoices(params) {
  return request.get('/invoices', { params, showLoading: false })
}

export function getInvoice(id) {
  return request.get(`/invoices/${id}`)
}

export function createInvoice(data) {
  return request.post('/invoices', data, { loadingText: '正在保存发票...' })
}

export function updateInvoice(id, data) {
  return request.put(`/invoices/${id}`, data, { loadingText: '正在保存发票...' })
}

export function validateInvoice(id) {
  return request.post(`/invoices/${id}/validate`, null, { loadingText: '正在校验发票...' })
}

export function syncInvoice(id) {
  return request.post(`/invoices/${id}/sync`, null, { loadingText: '正在同步小满...' })
}

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

export function getInvoicePrintUrl(id) {
  return `/api/invoice/invoices/${id}/export/print`
}
