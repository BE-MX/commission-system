import { receiptClient as request } from './clients'
const unwrap = promise => promise.then(res => res.data ?? res)
export const listReceipts = params => unwrap(request.get('', { params, showLoading: false }))
export const getReceipt = id => unwrap(request.get(`/${id}`, { showLoading: false }))
export const getReceiptOrders = params => unwrap(request.get('/order-options', { params, showLoading: false }))
export const getReceiptBalance = id => unwrap(request.get(`/order-balance/${id}`, { showLoading: false }))
export const getReceiptTypes = () => unwrap(request.get('/types', { showLoading: false }))
export const createReceipt = body => unwrap(request.post('', body))
export const updateReceipt = (id, body) => unwrap(request.patch(`/${id}`, body))
export const retryReceipt = id => unwrap(request.post(`/${id}/retry`))
export const voidReceipt = (id, reason) => unwrap(request.post(`/${id}/void`, { reason }))
export const reconcileReceipt = id => unwrap(request.post(`/${id}/reconcile`))
export const resolveReceipt = (id, body) => unwrap(request.post(`/${id}/resolve`, body))
export const getReceiptProof = id => request.get(`/attachments/${id}`, { responseType: 'blob', showLoading: false })
export function uploadReceiptProof(file, onProgress) {
  const data = new FormData()
  data.append('file', file)
  return unwrap(request.post('/attachments', data, { showLoading: false,
    onUploadProgress: e => onProgress?.(e.total ? Math.round(e.loaded / e.total * 100) : 0),
  }))
}

export const previewReceiptRemoteChange = id => unwrap(request.get(`/${id}/remote-change`))
export const acceptReceiptRemoteChange = (id, body) => unwrap(request.post(`/${id}/remote-change`, body))
