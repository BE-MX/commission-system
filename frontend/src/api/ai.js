import { aiClient as aiApi } from './clients'

// Subscription & Billing
export function getSubscriptions(params, config = {}) {
  return aiApi.get('/subscriptions', { ...config, params, showLoading: false })
}

export function upsertProviderBilling(id, data) {
  return aiApi.put(`/providers/${id}/billing`, data, { loadingText: '正在保存订阅信息...' })
}

export function confirmProviderRenew(id) {
  return aiApi.post(`/providers/${id}/renew-confirm`, {}, { loadingText: '正在确认续费...' })
}

export function getBalanceCheckpoints(id, params = {}, config = {}) {
  return aiApi.get(`/providers/${id}/balance-checkpoints`, { ...config, params, showLoading: false })
}

export function createBalanceCheckpoint(id, data) {
  return aiApi.post(`/providers/${id}/balance-checkpoints`, data, { loadingText: '正在登记余额...' })
}

export function getModelPrices(id, config = {}) {
  return aiApi.get(`/providers/${id}/model-prices`, { ...config, showLoading: false })
}

export function replaceModelPrices(id, items) {
  return aiApi.put(`/providers/${id}/model-prices`, { items }, { loadingText: '正在保存单价...' })
}

export function uploadProviderLogo(id, file) {
  const form = new FormData()
  form.append('file', file)
  return aiApi.put(`/providers/${id}/logo`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '正在上传 LOGO...',
  })
}

export function getProviderLogoBlob(id, config = {}) {
  return aiApi.get(`/providers/${id}/logo`, { ...config, responseType: 'blob', showLoading: false, suppressToast: true })
}

export function getFeatureCatalog(config = {}) {
  return aiApi.get('/feature-catalog', { ...config, showLoading: false })
}

// Provider
export function getProviders(params, config = {}) {
  return aiApi.get('/providers', { ...config, params, showLoading: false })
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
export function getPresets(params, config = {}) {
  return aiApi.get('/presets', { ...config, params, showLoading: false })
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
export function getLogs(params, config = {}) {
  return aiApi.get('/logs', { ...config, params, showLoading: false })
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
