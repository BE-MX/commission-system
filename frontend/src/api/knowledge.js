import { knowledgeClient } from './clients'

const SILENT = { showLoading: false, suppressToast: true }

export function uploadKnowledgeImage(libraryId, file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return knowledgeClient.post(`/libraries/${libraryId}/assets`, form, {
    ...SILENT,
    onUploadProgress: event => {
      if (event.total && onProgress) onProgress(Math.round(event.loaded / event.total * 100))
    },
  })
}

export function getKnowledgeImageBlob(assetId) {
  return knowledgeClient.get(`/assets/${assetId}/content`, {
    ...SILENT,
    responseType: 'blob',
  })
}

export function deleteTemporaryKnowledgeImage(assetId) {
  return knowledgeClient.delete(`/assets/${assetId}`, SILENT)
}

export function listAiProfiles(targetLibraryId = null, config = {}) {
  return knowledgeClient.get('/ai-profiles', {
    params: targetLibraryId ? { target_library_id: targetLibraryId } : {},
    showLoading: false,
    ...config,
  })
}

export function createAiProfile(data) {
  return knowledgeClient.post('/ai-profiles', data)
}

export function updateAiProfile(profileId, data) {
  return knowledgeClient.put(`/ai-profiles/${profileId}`, data)
}

export function deleteAiProfile(profileId) {
  return knowledgeClient.delete(`/ai-profiles/${profileId}`)
}

export function listAiPresetCandidates(config = {}) {
  return knowledgeClient.get('/ai-profiles/preset-candidates', { showLoading: false, ...config })
}

export function listAiLibraryCandidates(config = {}) {
  return knowledgeClient.get('/ai-profiles/library-candidates', { showLoading: false, ...config })
}

export function listAiProfileLogs(profileId, config = {}) {
  return knowledgeClient.get(`/ai-profiles/${profileId}/logs`, { showLoading: false, ...config })
}

export function previewAiRetrieval(profileId, data) {
  return knowledgeClient.post(`/ai-profiles/${profileId}/retrieval-preview`, data)
}

export function testAiProfile(profileId, data) {
  return knowledgeClient.post(`/ai-profiles/${profileId}/test`, data)
}

export function createDocumentAiJob(documentId, data) {
  return knowledgeClient.post(`/documents/${documentId}/ai-jobs`, data, SILENT)
}

export function listDocumentAiJobs(documentId, config = {}) {
  return knowledgeClient.get(`/documents/${documentId}/ai-jobs`, { ...SILENT, ...config })
}

export function getDocumentAiJob(jobId, config = {}) {
  return knowledgeClient.get(`/ai-jobs/${jobId}`, { ...SILENT, ...config })
}

export function cancelDocumentAiJob(jobId) {
  return knowledgeClient.post(`/ai-jobs/${jobId}/cancel`, {}, SILENT)
}

export function applyDocumentAiJob(jobId) {
  return knowledgeClient.post(`/ai-jobs/${jobId}/apply`, {}, SILENT)
}
