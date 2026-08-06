import { designImageClient } from './clients'

const SILENT_REQUEST = { showLoading: false, suppressToast: true }
const JOB_POLL_REQUEST = { ...SILENT_REQUEST, timeout: 20000 }

export function getConfig() {
  return designImageClient.get('/config', { showLoading: false })
}

export function createSession(data = {}) {
  return designImageClient.post('/sessions', data)
}

export function listSessions(params = {}) {
  return designImageClient.get('/sessions', { params, showLoading: false })
}

export function getSession(sessionId) {
  return designImageClient.get(`/sessions/${sessionId}`, { showLoading: false })
}

export function uploadAsset(sessionId, file) {
  const form = new FormData()
  form.append('file', file)
  return designImageClient.post(
    `/sessions/${sessionId}/assets`,
    form,
    { ...SILENT_REQUEST },
  )
}

export function deleteAsset(assetId) {
  return designImageClient.delete(`/assets/${assetId}`, { showLoading: false })
}

export function createTurn(sessionId, data) {
  return designImageClient.post(
    `/sessions/${sessionId}/turns`,
    data,
    { ...SILENT_REQUEST },
  )
}

export function getActiveJobs() {
  return designImageClient.get('/jobs/active', { ...JOB_POLL_REQUEST })
}

export function getJob(jobId) {
  return designImageClient.get(`/jobs/${jobId}`, { ...JOB_POLL_REQUEST })
}

export function retryJob(jobId, data) {
  return designImageClient.post(
    `/jobs/${jobId}/retry`,
    data,
    { ...SILENT_REQUEST },
  )
}

export function getAssetBlob(assetId, options = {}) {
  const normalized = typeof options === 'boolean' ? { download: options } : options
  const { thumbnail = false, download = false } = normalized
  return designImageClient.get(`/assets/${assetId}/content`, {
    ...SILENT_REQUEST,
    params: { thumbnail, download },
    responseType: 'blob',
  })
}

export function getUsage(params = {}) {
  return designImageClient.get('/usage', { params, showLoading: false })
}

export function listPromptTemplates(options = {}) {
  const { includeInactive = false } = options
  return designImageClient.get('/prompt-templates', {
    params: { include_inactive: includeInactive },
    showLoading: false,
  })
}

export function seedPromptTemplates() {
  return designImageClient.post('/prompt-templates/seed', {}, { ...SILENT_REQUEST })
}

export function createPromptTemplate(data) {
  return designImageClient.post('/prompt-templates', data, { ...SILENT_REQUEST })
}

export function updatePromptTemplate(templateId, data) {
  return designImageClient.put(`/prompt-templates/${templateId}`, data, { ...SILENT_REQUEST })
}

export function deletePromptTemplate(templateId) {
  return designImageClient.delete(`/prompt-templates/${templateId}`, { showLoading: false })
}

export function listLibraryAssets(scope = 'public') {
  return designImageClient.get('/library-assets', { params: { scope }, showLoading: false })
}

export function uploadLibraryAsset(scope, title, file) {
  const form = new FormData()
  form.append('scope', scope)
  form.append('title', title || '')
  form.append('file', file)
  return designImageClient.post('/library-assets', form, { ...SILENT_REQUEST })
}

export function deleteLibraryAsset(assetId) {
  return designImageClient.delete(`/library-assets/${assetId}`, { showLoading: false })
}

export function cloneLibraryAsset(assetId, sessionId) {
  return designImageClient.post(
    `/library-assets/${assetId}/clone`,
    { session_id: sessionId },
    { ...SILENT_REQUEST },
  )
}

export function getLibraryAssetBlob(assetId, options = {}) {
  const { thumbnail = false } = options
  return designImageClient.get(`/library-assets/${assetId}/content`, {
    ...SILENT_REQUEST,
    params: { thumbnail },
    responseType: 'blob',
  })
}
