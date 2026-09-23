// 发货检验 API（响应拦截器已解包信封，调用方取数用 res.data）
import { shippingClient } from './clients'

export const previewOutboundInvoiceSync = id => shippingClient.post(`/outbound-records/${encodeURIComponent(id)}/invoice-sync/preview`, {}, { timeout: 180000 })
export const syncOutboundInvoice = (id, expected_version, check_only = false) => shippingClient.post(`/outbound-records/${encodeURIComponent(id)}/invoice-sync`, { expected_version, check_only }, { timeout: 180000 })

// 出库单检验状态（与后端 shipping_inspection 同一套口径）
export const INSPECTION_STATUS_LABELS = { none: '未检验', draft: '检验中', submitted: '已提交' }
export const INSPECTION_STATUS_TAGS = { none: 'info', draft: 'warning', submitted: 'success' }

// ── OKKI 出库单 ──
export function listOutboundRecords(params) {
  return shippingClient.get('/outbound-records', { params })
}

export function deleteOutboundRecord(id) {
  return shippingClient.delete(`/outbound-records/${encodeURIComponent(id)}`)
}

export function getOutboundPrintData(id) {
  return shippingClient.get(`/outbound-records/${id}/print-data`)
}

export function downloadOutboundWord(id) {
  return shippingClient.get(`/outbound-records/${encodeURIComponent(id)}/word`, { responseType: 'blob' })
}

export function recallInspectionRecord(id, editVersion) {
  return shippingClient.post(`/records/${id}/recall`, { edit_version: editVersion })
}

// ── 验货单（已提交的发货检验单）──
export function listInspectionRecords(params) {
  return shippingClient.get('/records', { params })
}

export function getInspectionRecord(id) {
  return shippingClient.get(`/records/${id}`)
}

// 图片走鉴权端点，浏览器 <img src> 不带 token —— 一律取 blob 再转 object URL
// （同 domestic 参考图的做法，见 src/api/domestic.js）
export async function fetchImageBlobUrl(path) {
  const res = await shippingClient.get(`/images/${path}`, { responseType: 'blob' })
  return URL.createObjectURL(res.data)
}

export async function fetchVideoBlobUrl(path) {
  const res = await shippingClient.get(`/images/${path}`, { responseType: 'blob', timeout: 300000 })
  return URL.createObjectURL(res.data)
}

// 打印文档要塞进 iframe，blob URL 在跨文档场景不可靠，一律转 data URL
export async function fetchImageDataUrl(path) {
  const res = await shippingClient.get(`/images/${path}`, { responseType: 'blob' })
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(res.data)
  })
}

export function downloadInspectionPdf(id, version) {
  return shippingClient.get(`/records/${encodeURIComponent(id)}/pdf`, {
    params: { edit_version: version }, responseType: 'blob', suppressToast: true, redirectOnUnauthorized: false,
  })
}

export const recoverOutboundDeletion = (id, body) => shippingClient.post(`/outbound-records/${encodeURIComponent(id)}/delete-recovery`, body)
