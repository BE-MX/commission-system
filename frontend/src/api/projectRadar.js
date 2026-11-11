import { projectRadarClient as api, projectRadarPublicClient as publicApi } from './clients'

export function listRadarSubscriptions(params, config = {}) {
  return api.get('/subscriptions', { ...config, params, showLoading: false })
}

export function ingestRadar(rawInput, config = {}) {
  return api.post('/ingest', { raw_input: rawInput }, { ...config, showLoading: false })
}

export function getRadarJob(id, config = {}) {
  return api.get(`/jobs/${id}`, { ...config, showLoading: false, suppressToast: true })
}

export function selectRadarCandidates(jobId, selection) {
  return api.post(`/jobs/${jobId}/select`, { selection })
}

export function getRadarSubscription(id, config = {}) {
  return api.get(`/subscriptions/${id}`, { ...config, showLoading: false })
}

export function patchRadarSubscription(id, data, config = {}) {
  return api.patch(`/subscriptions/${id}`, data, { ...config, showLoading: false })
}

export function removeRadarSubscription(id) {
  return api.delete(`/subscriptions/${id}`)
}

export function reanalyzeRadarSubscription(id) {
  return api.post(`/subscriptions/${id}/reanalyze`)
}

export function getRadarHealth(config = {}) {
  return api.get('/health', { ...config, showLoading: false, suppressToast: true })
}

export function getRadarSettings(config = {}) {
  return api.get('/settings', { ...config, showLoading: false })
}

export function saveRadarSettings(data) {
  return api.put('/settings', data)
}

export function saveRadarGlobalSettings(data) {
  return api.put('/settings/global', data)
}

export function getPublicRadarSubscription(id, params, config = {}) {
  return publicApi.get(`/public/${id}`, { ...config, params, showLoading: false })
}
