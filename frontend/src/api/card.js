/** 名片管家 API（/api/card/admin/*，card:read / card:write） */
import { cardClient } from './clients'
import { compressImage } from '@/utils/compressImage'

// ---------- 业务员档案 ----------
export function getSalespersons() {
  return cardClient.get('/admin/salespersons')
}

export function upsertSalesperson(data) {
  return cardClient.post('/admin/salespersons', data)
}

// ---------- 客户档案 ----------
export function getCustomers(params) {
  return cardClient.get('/admin/customers', { params })
}

export function createCustomer(data) {
  return cardClient.post('/admin/customers', data)
}

export function updateCustomer(id, data) {
  return cardClient.put(`/admin/customers/${id}`, data)
}

export function deleteCustomer(id) {
  return cardClient.delete(`/admin/customers/${id}`)
}

// ---------- 沟通纪要 ----------
export function getEntries(customerId) {
  return cardClient.get(`/admin/customers/${customerId}/entries`)
}

export function createEntry(customerId, data) {
  return cardClient.post(`/admin/customers/${customerId}/entries`, data)
}

export function deleteEntry(entryId) {
  return cardClient.delete(`/admin/entries/${entryId}`)
}

/** AppUpload 注入用：async (File, onProgress) => ({ path, url, name })
 * 先端上压缩再传（compressImage 注释里有为什么必须压）；跨境隧道慢，超时单独放宽。 */
export async function uploadAttachment(file, onProgress) {
  const prepared = await compressImage(file)
  const form = new FormData()
  form.append('file', prepared, prepared.name)
  const res = await cardClient.post('/admin/attachments', form, {
    timeout: 180000,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: e => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
  const payload = res.data ?? res
  return { path: payload.attachment_path, url: payload.url }
}

// ---------- 询盘 ----------
export function getInquiries(params) {
  return cardClient.get('/admin/inquiries', { params })
}

export function updateInquiry(id, data) {
  return cardClient.put(`/admin/inquiries/${id}`, data)
}
