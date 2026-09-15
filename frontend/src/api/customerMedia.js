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

// ── 客户标签（tag_scope='customer' 维度） ────────────────
export const getCustomerTagDimensions = () => customerMediaClient.get('/tags/dimensions', { showLoading: false })
export const validateCustomerTags = tagNames => customerMediaClient.post('/tags/validate', { tag_names: tagNames }, {
  showLoading: false,
  timeout: 30000,
})
// autoCreateTags: { 标签名: dimension_id }，幂等；确认动作在前端完成
export const resolveCustomerTags = autoCreateTags => customerMediaClient.post('/tags/resolve', { auto_create_tags: autoCreateTags }, {
  loadingText: '正在创建标签...',
  timeout: 30000,
})
// 同名复用返回已有值
export const createCustomerTagValue = (dimensionId, value) => customerMediaClient.post('/tags/values', { dimension_id: dimensionId, value })
// 按维度全量覆盖：tags = [{dimension_id, tag_value_ids}]，空数组清该维度
export const updateMediaAssetTags = (batchId, assetId, tags) => customerMediaClient.patch(`/batches/${batchId}/assets/${assetId}/tags`, { tags })

export const uploadMediaAsset = (batchId, file, onUploadProgress, { directoryId, directoryName, tags } = {}) => {
  const data = new FormData()
  data.append('file', file)
  if (directoryId != null) data.append('directory_id', String(directoryId))
  else if (directoryName) data.append('directory_name', directoryName)
  if (tags?.length) data.append('tags_json', JSON.stringify(tags))
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
export const getSalesPortalCustomer = (customerId, tagValueIds) => customerMediaClient.get(`/sales-portal/customers/${encodeURIComponent(customerId)}`, {
  showLoading: false,
  suppressToast: true,
  params: tagValueIds?.length ? { tag_value_ids: tagValueIds.join(',') } : undefined,
})
