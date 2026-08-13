import { customerMediaClient } from './clients'

export const searchMediaCustomers = search => customerMediaClient.get('/customers', { params: { search }, showLoading: false })
export const getTaskMediaBatch = taskId => customerMediaClient.get(`/tasks/${taskId}/batch`)
export const uploadMediaAsset = (batchId, file, onUploadProgress) => {
  const data = new FormData()
  data.append('file', file)
  return customerMediaClient.post(`/batches/${batchId}/assets`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0,
    onUploadProgress,
    showLoading: false,
  })
}
export const deleteMediaAsset = (batchId, assetId) => customerMediaClient.delete(`/batches/${batchId}/assets/${assetId}`)
export const submitMediaBatch = (batchId, lockVersion) => customerMediaClient.post(`/batches/${batchId}/submit`, { lock_version: lockVersion })
export const getMediaReviews = (status = 'pending_review') => customerMediaClient.get('/reviews', { params: { status }, showLoading: false })
export const reviewMediaBatch = (batchId, data) => customerMediaClient.post(`/batches/${batchId}/review`, data)
export const unpublishMediaBatch = (batchId, comment) => customerMediaClient.post(`/batches/${batchId}/unpublish`, null, { params: { comment } })
export const getPortalAccounts = search => customerMediaClient.get('/portal-accounts', { params: { search }, showLoading: false })
export const createPortalAccount = data => customerMediaClient.post('/portal-accounts', data)
export const updatePortalAccount = (id, data) => customerMediaClient.patch(`/portal-accounts/${id}`, data)
