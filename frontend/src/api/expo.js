/**
 * 展会 AI 假发试戴 API（/api/expo）。
 * 后端统一 ok() 信封 {code,message,data}，拦截器返回整个响应体，取数用 res.data。
 */
import { expoClient } from './clients'

// ── 试戴主流程（展位设备） ──
export function registerCustomer(data) {
  return expoClient.post('/register', data, { showLoading: false })
}

export function createSession(customerId, photoBlob, mode = 'tryon') {
  const form = new FormData()
  form.append('photo', photoBlob, 'photo.jpg')
  return expoClient.post(`/sessions?customer_id=${customerId}&mode=${mode}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    showLoading: false,
  })
}

export function getSession(sessionId, { internal = false } = {}) {
  return expoClient.get(`/sessions/${sessionId}`, {
    params: { internal: internal ? 1 : 0 },
    showLoading: false,
  })
}

export function generateResults(sessionId, { wigIds = null, batch = 0, hairColorId = null, sceneKey = null, sceneKeys = null } = {}) {
  return expoClient.post(`/sessions/${sessionId}/generate`, {
    wig_ids: wigIds, batch, hair_color_id: hairColorId, scene_key: sceneKey, scene_keys: sceneKeys,
  }, { showLoading: false })
}

export function getHairColors(params) {
  return expoClient.get('/hair-colors', { params, showLoading: false })
}

export function getScenes(params) {
  return expoClient.get('/scenes', { params, showLoading: false })
}

export function setReaction(resultId, reaction) {
  return expoClient.post(`/results/${resultId}/reaction`, { reaction }, { showLoading: false })
}

export function submitFeedback(customerId, data) {
  return expoClient.post(`/customers/${customerId}/feedback`, data)
}

// ── 线索台（PC） ──
export function getLeads(params) {
  return expoClient.get('/leads', { params })
}

export function getLeadDetail(customerId, { silent = false } = {}) {
  // silent：详情抽屉的后台轮询用——不弹全屏 loading、失败不弹 toast
  return expoClient.get(`/leads/${customerId}`, silent ? { showLoading: false, suppressToast: true } : {})
}

export function deleteCustomer(customerId) {
  return expoClient.delete(`/customers/${customerId}`)
}

// ── 发型库（PC） ──
export function getWigs(params) {
  return expoClient.get('/wigs', { params })
}

export function createWig(data) {
  return expoClient.post('/wigs', data)
}

export function updateWig(id, data) {
  return expoClient.put(`/wigs/${id}`, data)
}

export function deleteWig(id) {
  return expoClient.delete(`/wigs/${id}`)
}

export function uploadWigPhoto(file) {
  const form = new FormData()
  form.append('photo', file)
  return expoClient.post('/wigs/upload-photo', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ── 发色库（PC；列表复用主流程的 getHairColors） ──
export function createHairColor(data) {
  return expoClient.post('/hair-colors', data)
}

export function updateHairColor(id, data) {
  return expoClient.put(`/hair-colors/${id}`, data)
}

export function deleteHairColor(id) {
  return expoClient.delete(`/hair-colors/${id}`)
}

export function uploadHairColorSwatch(file) {
  const form = new FormData()
  form.append('photo', file)
  return expoClient.post('/hair-colors/upload-swatch', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ── 话术卡库（PC） ──
export function getScripts(params) {
  return expoClient.get('/scripts', { params })
}

export function createScript(data) {
  return expoClient.post('/scripts', data)
}

export function updateScript(id, data) {
  return expoClient.put(`/scripts/${id}`, data)
}

export function seedScripts() {
  return expoClient.post('/scripts/seed')
}
