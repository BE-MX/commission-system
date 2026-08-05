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

export function getActiveJob() {
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
