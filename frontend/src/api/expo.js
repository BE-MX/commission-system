/**
 * 展会 AI 假发试戴 API（/api/expo）。
 * 后端统一 ok() 信封 {code,message,data}，拦截器返回整个响应体，取数用 res.data。
 */
import { expoClient } from './clients'

// ── 试戴主流程（展位设备） ──
// kiosk 是客户共享屏：所有流程端点必须 suppressToast，禁止拦截器把 axios 原始
// 报错（英文 "Network Error"）弹到客户面前——错误反馈统一走 useTryOnFlow.errorText
// 的中文文案与重试路径（2026-07-14 展会现场实case）
const KIOSK = { showLoading: false, suppressToast: true }

export function registerCustomer(data) {
  return expoClient.post('/register', data, { ...KIOSK })
}

// kiosk「返回上一步」修改登记信息：更新既有客户，不重复建档
export function updateCustomer(customerId, data) {
  return expoClient.put(`/customers/${customerId}`, data, { ...KIOSK })
}

// ── kiosk 销售面板（展位设备；手机号脱敏，话术不含 internal 发况） ──
export function getKioskLeads(params) {
  return expoClient.get('/kiosk/leads', { params, ...KIOSK })
}

export function getKioskStrategy(customerId) {
  return expoClient.get(`/kiosk/leads/${customerId}/strategy`, { ...KIOSK })
}

// ── 扫码上传照片（2026-08-01）──
export function createUploadTicket(customerId) {
  return expoClient.post(`/kiosk/upload-ticket?customer_id=${customerId}`, null, { ...KIOSK })
}

export function getPendingPhoto(customerId) {
  return expoClient.get('/kiosk/pending-photo', {
    params: { customer_id: customerId },
    // 与会话轮询同口径的短超时：弱网下不让在途请求长期占坑
    timeout: 10000,
    ...KIOSK,
  })
}

// photoBlob=现场拍照 / pendingName=扫码上传后待取的文件名，二选一随表单提交给后端
export function createSession(customerId, photoBlob, mode = 'tryon', pendingName = null) {
  const form = new FormData()
  if (pendingName) form.append('pending_photo', pendingName)
  else form.append('photo', photoBlob, 'photo.jpg')
  return expoClient.post(`/sessions?customer_id=${customerId}&mode=${mode}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    ...KIOSK,
  })
}

export function getSession(sessionId, { internal = false } = {}) {
  return expoClient.get(`/sessions/${sessionId}`, {
    params: { internal: internal ? 1 : 0 },
    // 轮询专用短超时：expoClient 默认 300s，弱网下会让在途请求长期占坑，
    // 轮询守卫（useTryOnFlow.poll 的 pollBusy）会被卡死 5 分钟
    timeout: 10000,
    ...KIOSK,
  })
}

export function contactExpoAdmin(sessionId) {
  return expoClient.post(`/sessions/${sessionId}/contact-admin`, null, { ...KIOSK })
}

export function generateResults(sessionId, { wigIds = null, batch = 0, hairColorId = null, sceneKey = null, sceneKeys = null, quality = null, promptVariant = null } = {}) {
  return expoClient.post(`/sessions/${sessionId}/generate`, {
    wig_ids: wigIds, batch, hair_color_id: hairColorId, scene_key: sceneKey, scene_keys: sceneKeys,
    quality, prompt_variant: promptVariant,
  }, { ...KIOSK })
}

// 发色/场景列表被 kiosk 与 PC 管理页（HairColorLibrary/SceneImages）共用：
// 仅 kiosk 调用传 { kiosk: true } 抑制 toast，PC 侧保留拦截器统一报错
export function getHairColors(params, { kiosk = false } = {}) {
  return expoClient.get('/hair-colors', { params, ...(kiosk ? KIOSK : { showLoading: false }) })
}

export function getScenes(params, { kiosk = false } = {}) {
  return expoClient.get('/scenes', { params, ...(kiosk ? KIOSK : { showLoading: false }) })
}

// kiosk「从发型库选择」：启用发型轻量列表（id/name/series/cover_url）
export function getWigPicker() {
  return expoClient.get('/wigs/picker', { ...KIOSK })
}

// kiosk：某发型已备三角度图的发色列表（发色随发型过滤，「原色」由前端恒定提供）
export function getWigColors(wigId) {
  return expoClient.get(`/wigs/${wigId}/colors`, { ...KIOSK })
}

// ── 场景示意图管理（PC；列表复用 getScenes({ mode: 'tryon' })） ──
export function uploadSceneImage(key, file) {
  const form = new FormData()
  form.append('photo', file)
  return expoClient.post(`/scenes/${key}/image`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteSceneImage(key) {
  return expoClient.delete(`/scenes/${key}/image`)
}

export function setReaction(resultId, reaction) {
  return expoClient.post(`/results/${resultId}/reaction`, { reaction }, { ...KIOSK })
}

export function submitFeedback(customerId, data) {
  return expoClient.post(`/customers/${customerId}/feedback`, data, { ...KIOSK })
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

// ── 发型×发色组合参考图（PC 管理端） ──
export function getWigColorImages(wigId) {
  return expoClient.get(`/wigs/${wigId}/color-images`)
}

export function saveWigColorImages(wigId, colorId, data) {
  return expoClient.put(`/wigs/${wigId}/color-images/${colorId}`, data)
}

export function deleteWigColorImages(wigId, colorId) {
  return expoClient.delete(`/wigs/${wigId}/color-images/${colorId}`)
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

// 删发色前查影响面：被多少发型备了三角度图（删发色会一并清除这些组合图）
export function getHairColorUsage(id) {
  return expoClient.get(`/hair-colors/${id}/usage`, { showLoading: false })
}

export function uploadHairColorSwatch(file) {
  const form = new FormData()
  form.append('photo', file)
  return expoClient.post('/hair-colors/upload-swatch', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ── 门店与额度（2026-08-06） ──
// 当前账号绑定门店的额度快照（kiosk 状态栏 / PC 线索台工具栏共用）：
// 未绑定门店是正常态（bound=false），两侧都静默处理，不当错误弹 toast
export function getMyStoreQuota({ kiosk = false } = {}) {
  return expoClient.get('/stores/quota', kiosk
    ? { ...KIOSK }
    : { showLoading: false, suppressToast: true })
}

// 启用门店选项（线索台 expo_lead:read_all 筛选用，轻量 id/name/code）
export function getStoreOptions() {
  return expoClient.get('/stores/options', { showLoading: false })
}

// ── 门店管理（PC，expo_store:admin/recharge） ──
export function getStores(params) {
  return expoClient.get('/stores', { params })
}

export function createStore(data) {
  return expoClient.post('/stores', data)
}

export function updateStore(id, data) {
  return expoClient.put(`/stores/${id}`, data)
}

export function toggleStore(id) {
  return expoClient.post(`/stores/${id}/toggle`)
}

export function getStoreUsers(id) {
  return expoClient.get(`/stores/${id}/users`)
}

export function bindStoreUser(id, data) {
  return expoClient.post(`/stores/${id}/users`, data)
}

export function unbindStoreUser(id, userId) {
  return expoClient.delete(`/stores/${id}/users/${userId}`)
}

export function getStoreQuota(id) {
  return expoClient.get(`/stores/${id}/quota`)
}

export function rechargeQuota(id, data) {
  return expoClient.post(`/stores/${id}/quota/recharge`, data)
}

export function listQuotaRecords(id, params) {
  return expoClient.get(`/stores/${id}/quota/records`, { params })
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
