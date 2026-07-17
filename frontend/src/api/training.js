// 培训速递 API（响应拦截器已解包信封，调用方取数用 res.data）
import { trainingClient } from './clients'

export function listDigests(params) {
  return trainingClient.get('', { params })
}

export function createDigest(data) {
  return trainingClient.post('', data)
}

export function getDigest(id) {
  return trainingClient.get(`/${id}`)
}

export function updateDigest(id, data) {
  return trainingClient.put(`/${id}`, data)
}

export function deleteDigest(id) {
  return trainingClient.delete(`/${id}`)
}

export function uploadDigestFile(id, file) {
  const form = new FormData()
  form.append('file', file)
  return trainingClient.post(`/${id}/files`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  })
}

export function deleteDigestFile(fileId) {
  return trainingClient.delete(`/files/${fileId}`)
}

// 附件下载：浏览器直链不带 JWT（cerebrum 2026-07-12），必须 axios blob
export function downloadDigestFile(fileId) {
  return trainingClient.get(`/files/${fileId}/download`, {
    responseType: 'blob',
    timeout: 300000,
  })
}

// AI 提炼：多模态调用最长可达数分钟，单独放长超时
export function generateDraft(id, textMaterials) {
  return trainingClient.post(
    `/${id}/draft`,
    { text_materials: textMaterials },
    { timeout: 300000, loadingText: 'AI 提炼中…' },
  )
}

export function publishDigest(id) {
  return trainingClient.post(`/${id}/publish`)
}

export function pushDigest(id) {
  return trainingClient.post(`/${id}/push`)
}

export function toggleUseful(id) {
  return trainingClient.post(`/${id}/useful`)
}
