import { aiClient as aiApi } from './clients'

// Provider
export function getProviders(params) {
  return aiApi.get('/providers', { params, showLoading: false })
}

export function createProvider(data) {
  return aiApi.post('/providers', data, { loadingText: '正在保存...' })
}

export function updateProvider(id, data) {
  return aiApi.put(`/providers/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteProvider(id) {
  return aiApi.delete(`/providers/${id}`)
}

export function testProvider(id) {
  return aiApi.post(`/providers/${id}/test`, {}, { loadingText: '连通性测试中...' })
}

// Preset
export function getPresets(params) {
  return aiApi.get('/presets', { params, showLoading: false })
}

export function createPreset(data) {
  return aiApi.post('/presets', data, { loadingText: '正在保存...' })
}

export function updatePreset(id, data) {
  return aiApi.put(`/presets/${id}`, data, { loadingText: '正在保存...' })
}

export function deletePreset(id) {
  return aiApi.delete(`/presets/${id}`)
}

export function testPreset(id, testMessage, imageFile = null, referenceImageFile = null) {
  if (imageFile) {
    const form = new FormData()
    form.append('test_message', testMessage)
    form.append('image', imageFile)
    if (referenceImageFile) {
      form.append('reference_image', referenceImageFile)
    }
    return aiApi.post(`/presets/${id}/test-multimodal`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      loadingText: '测试中...',
    })
  }
  return aiApi.post(`/presets/${id}/test`, { test_message: testMessage }, { loadingText: '测试中...' })
}

// Call Log
export function getLogs(params) {
  return aiApi.get('/logs', { params, showLoading: false })
}

export function getLogDetail(id) {
  return aiApi.get(`/logs/${id}`)
}

// Invoke
export function chat(data) {
  return aiApi.post('/chat', data, { loadingText: 'AI 思考中...' })
}

export function delegate(data) {
  return aiApi.post('/delegate', data, { loadingText: '提交任务中...' })
}

export function getTaskResult(taskId) {
  return aiApi.get(`/tasks/${taskId}`, { showLoading: false })
}

export default aiApi
