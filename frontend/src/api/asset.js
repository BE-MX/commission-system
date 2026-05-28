import { assetClient } from './clients'

// ── 标签维度 ────────────────────────────────────────────
export function getTagDimensions() {
  return assetClient.get('/tags/dimensions', { showLoading: false })
}

export function createDimension(data) {
  return assetClient.post('/tags/dimensions', data)
}

export function updateDimension(dimId, data) {
  return assetClient.put(`/tags/dimensions/${dimId}`, data)
}

export function deleteDimension(dimId) {
  return assetClient.delete(`/tags/dimensions/${dimId}`)
}

export function createTagValue(dimensionId, data) {
  return assetClient.post(`/tags/dimensions/${dimensionId}/values`, data)
}

export function updateTagValue(valueId, data) {
  return assetClient.put(`/tags/values/${valueId}`, data)
}

export function deleteTagValue(valueId) {
  return assetClient.delete(`/tags/values/${valueId}`)
}

export function uploadTagImage(file) {
  const formData = new FormData()
  formData.append('file', file)
  return assetClient.post('/tag-image-upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '上传中...',
    timeout: 30000,
  })
}

// ── 素材 ────────────────────────────────────────────────
export function getAssetList(params) {
  return assetClient.get('/list', { params, showLoading: false })
}

export function getAssetDetail(assetId) {
  return assetClient.get(`/${assetId}`, { showLoading: false })
}

export function uploadAsset(data) {
  return assetClient.post('/upload', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '上传中...',
    timeout: 300000,
  })
}

export function updateAssetTags(assetId, data) {
  return assetClient.patch(`/${assetId}/tags`, data)
}

export function updateAssetStatus(assetId, data) {
  return assetClient.patch(`/${assetId}/status`, data)
}

export function uploadVersion(assetId, data) {
  return assetClient.post(`/${assetId}/version`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '上传中...',
    timeout: 300000,
  })
}

export function deleteAsset(assetId) {
  return assetClient.delete(`/${assetId}`)
}

export function analyzeAsset(assetId) {
  return assetClient.post(`/${assetId}/analyze`, {}, { loadingText: 'AI 分析中...', timeout: 60000 })
}

export function analyzePreview(fileName, directoryPath) {
  return assetClient.post('/analyze-preview', null, {
    params: { file_name: fileName, directory_path: directoryPath },
    loadingText: 'AI 分析中...',
    timeout: 60000,
  })
}

// ── 文件夹批量上传 ──────────────────────────────────────
export function validateFolderUpload(folderPath) {
  return assetClient.post('/folder-upload/validate', { folder_path: folderPath }, {
    loadingText: '正在扫描文件夹...',
    timeout: 30000,
  })
}

export function previewFolderUpload(folderPath, tagMapping) {
  return assetClient.post('/folder-upload/preview', {
    folder_path: folderPath,
    tag_mapping: tagMapping,
  }, {
    loadingText: '正在生成预览...',
    timeout: 30000,
  })
}

export function executeFolderUpload(folderPath, tagMapping, permission, extraTags, updateDuplicates = true) {
  return assetClient.post('/folder-upload/execute', {
    folder_path: folderPath,
    tag_mapping: tagMapping,
    permission,
    extra_tags: extraTags,
    update_duplicates: updateDuplicates,
  }, {
    loadingText: '正在入库...',
    timeout: 600000,
  })
}

export function getFolderUploadStatus(jobId) {
  return assetClient.get(`/folder-upload/status/${jobId}`, { showLoading: false })
}

export function batchDownload(assetIds) {
  return assetClient.post('/batch/download', { asset_ids: assetIds }, {
    responseType: 'blob',
    loadingText: '打包中...',
    timeout: 120000,
  })
}

export function downloadAsset(assetId) {
  return assetClient.get(`/${assetId}/download`, { responseType: 'blob' })
}

// ── 收藏 ────────────────────────────────────────────────
export function getFavoriteFolders() {
  return assetClient.get('/favorites/folders', { showLoading: false })
}

export function createFavoriteFolder(data) {
  return assetClient.post('/favorites/folders', data)
}

export function updateFavoriteFolder(folderId, data) {
  return assetClient.put(`/favorites/folders/${folderId}`, data)
}

export function deleteFavoriteFolder(folderId) {
  return assetClient.delete(`/favorites/folders/${folderId}`)
}

export function getFavoriteItems(folderId) {
  return assetClient.get(`/favorites/folders/${folderId}/items`, { showLoading: false })
}

export function addFavoriteItem(folderId, data) {
  return assetClient.post(`/favorites/folders/${folderId}/items`, data)
}

export function removeFavoriteItem(folderId, itemId) {
  return assetClient.delete(`/favorites/folders/${folderId}/items/${itemId}`)
}

export function shareFolder(folderId, expiresHours = 168) {
  return assetClient.post(`/favorites/folders/${folderId}/share`, null, {
    params: { expires_hours: expiresHours },
  })
}

export function revokeShare(folderId) {
  return assetClient.post(`/favorites/folders/${folderId}/revoke-share`)
}

// ── 统计 ────────────────────────────────────────────────
export function getDownloadStats() {
  return assetClient.get('/stats/downloads', { showLoading: false })
}

export function getTopDownloaded(limit = 20) {
  return assetClient.get('/stats/downloads/top', { params: { limit }, showLoading: false })
}

export function getDownloadTrend(days = 30) {
  return assetClient.get('/stats/downloads/trend', { params: { days }, showLoading: false })
}
