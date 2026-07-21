// 培训速递 API（响应拦截器已解包信封，调用方取数用 res.data）
import { trainingClient } from './clients'

// 附件类型白名单，与后端 schemas.FILE_TYPE_OPTIONS 同一套口径
export const FILE_TYPE_OPTIONS = [
  { value: 'courseware', label: '课件讲义' },
  { value: 'photo', label: '现场照片' },
  { value: 'recording', label: '录音录像' },
  { value: 'notes', label: '笔记文档' },
  { value: 'other', label: '其他' },
]

export const FILE_TYPE_LABELS = Object.fromEntries(FILE_TYPE_OPTIONS.map(o => [o.value, o.label]))

// 按扩展名自动识别附件类型（上传栏默认「自动识别」，用户可整批覆盖）
const EXT_TYPE_MAP = {
  jpg: 'photo', jpeg: 'photo', png: 'photo', webp: 'photo',
  mp4: 'recording', mp3: 'recording', m4a: 'recording',
  pdf: 'courseware', ppt: 'courseware', pptx: 'courseware',
  doc: 'courseware', docx: 'courseware', xls: 'courseware', xlsx: 'courseware',
  txt: 'notes', md: 'notes',
}

export function inferFileType(fileName) {
  const ext = (fileName || '').split('.').pop().toLowerCase()
  return EXT_TYPE_MAP[ext] || 'other'
}

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

export function uploadDigestFile(id, file, { fileType = 'other', remark = '', onProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('file_type', fileType)
  form.append('remark', remark)
  return trainingClient.post(`/${id}/files`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    // e.total 在个别代理链路下可能缺失，缺失时不回调，进度条走 indeterminate
    onUploadProgress: e => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export function updateDigestFileMeta(fileId, data) {
  return trainingClient.patch(`/files/${fileId}`, data)
}

export function deleteDigestFile(fileId) {
  return trainingClient.delete(`/files/${fileId}`)
}

// 附件下载：浏览器直链不带 JWT（cerebrum 2026-07-12），必须 axios blob；
// 404 静默交给调用方给中文提示（blob 错误体拦截器解不出 detail）
export function downloadDigestFile(fileId) {
  return trainingClient.get(`/files/${fileId}/download`, {
    responseType: 'blob',
    timeout: 300000,
    suppressNotFound: true,
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
