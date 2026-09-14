import { customerMediaClient } from './clients'
import { resolveBatchMediaUrls } from './customerMediaUrls'

customerMediaClient.interceptors.response.use(response => {
  response.data = resolveBatchMediaUrls(response.data, customerMediaClient.defaults.baseURL, window.location.origin)
  return response
})

export const searchMediaCustomers = search => customerMediaClient.get('/customers', { params: { search }, showLoading: false })
export const getTaskMediaBatch = taskId => customerMediaClient.get(`/tasks/${taskId}/batch`)
export const getMediaDirectories = batchId => customerMediaClient.get(`/batches/${batchId}/directories`, { showLoading: false })
export const createMediaDirectory = (batchId, name) => customerMediaClient.post(`/batches/${batchId}/directories`, { name })
export const renameMediaDirectory = (batchId, directoryId, name) => customerMediaClient.patch(`/batches/${batchId}/directories/${directoryId}`, { name })
export const uploadMediaAsset = (batchId, file, onUploadProgress, { directoryId, directoryName } = {}) => {
  const data = new FormData()
  data.append('file', file)
  if (directoryId != null) data.append('directory_id', String(directoryId))
  else if (directoryName) data.append('directory_name', directoryName)
  return customerMediaClient.post(`/batches/${batchId}/assets`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0,
    onUploadProgress,
    showLoading: false,
  })
}
export const deleteMediaAsset = (batchId, assetId) => customerMediaClient.delete(`/batches/${batchId}/assets/${assetId}`)
export const deleteMediaDirectory = (batchId, directoryId) => customerMediaClient.delete(`/batches/${batchId}/directories/${directoryId}`)
export const submitMediaBatch = (batchId, lockVersion) => customerMediaClient.post(`/batches/${batchId}/submit`, { lock_version: lockVersion })
export const getMediaReviews = (status = 'pending_review') => customerMediaClient.get('/reviews', { params: { status }, showLoading: false })
export const reviewMediaBatch = (batchId, data) => customerMediaClient.post(`/batches/${batchId}/review`, data)
export const unpublishMediaBatch = (batchId, comment) => customerMediaClient.post(`/batches/${batchId}/unpublish`, null, { params: { comment } })
export const getPortalAccounts = search => customerMediaClient.get('/portal-accounts', { params: { search }, showLoading: false })
export const createPortalAccount = data => customerMediaClient.post('/portal-accounts', data)
export const updatePortalAccount = (id, data) => customerMediaClient.patch(`/portal-accounts/${id}`, data)
export const getSalesPortalCustomers = (search = '') => customerMediaClient.get('/sales-portal/customers', {
  params: { search }, showLoading: false, suppressToast: true,
})
export const getSalesPortalCustomer = customerId => customerMediaClient.get(`/sales-portal/customers/${encodeURIComponent(customerId)}`, {
  showLoading: false, suppressToast: true,
})
