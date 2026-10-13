import { whatsappClient } from './clients'

export function listWhatsAppAccounts(config = {}) {
  return whatsappClient.get('/accounts', config)
}

export function createWhatsAppBindSession(payload = {}) {
  return whatsappClient.post('/bind-sessions', payload)
}

export function getWhatsAppBindSession(bindSessionUid) {
  return whatsappClient.get(`/bind-sessions/${bindSessionUid}`)
}

export function revokeWhatsAppAccount(accountUid) {
  return whatsappClient.post(`/accounts/${accountUid}/revoke`)
}

export function pullWhatsAppResource(payload) {
  return whatsappClient.post('/sync/pull', payload)
}

export function listWhatsAppConversations(params, config = {}) {
  return whatsappClient.get('/conversations', { params, ...config })
}

export function listWhatsAppMessages(params, config = {}) {
  return whatsappClient.get('/messages', { params, ...config })
}

export function updateWhatsAppConsent(accountUid, payload) {
  return whatsappClient.put(`/accounts/${accountUid}/consent`, payload)
}

export function listWhatsAppReaderCandidates(accountUid, q = '', config = {}) {
  return whatsappClient.get(`/accounts/${accountUid}/reader-candidates`, { params: { q }, ...config })
}

export function confirmWhatsAppDeviceRemoval(accountUid) {
  return whatsappClient.post(`/accounts/${accountUid}/revoke-confirmation`, { phone_device_removed: true })
}

export function getWhatsAppAssistantOptions(accountUid, config = {}) {
  return whatsappClient.get('/ai-assistant/options', { params: { account_uid: accountUid }, ...config })
}

export function createWhatsAppAssistantRun(payload, config = {}) {
  return whatsappClient.post('/ai-assistant/runs', payload, config)
}

export function listWhatsAppAssistantRuns(accountUid, config = {}) {
  return whatsappClient.get('/ai-assistant/runs', { params: { account_uid: accountUid }, ...config })
}

export function getWhatsAppAssistantRun(runUid, config = {}) {
  return whatsappClient.get(`/ai-assistant/runs/${encodeURIComponent(runUid)}`, config)
}

export function getWhatsAppAssistantRequest(requestUid, accountUid, config = {}) {
  return whatsappClient.get(`/ai-assistant/runs/requests/${encodeURIComponent(requestUid)}`, { params: { account_uid: accountUid }, ...config })
}

export function updateWhatsAppAssistantTask(runUid, taskUid, completed, config = {}) {
  return whatsappClient.patch(`/ai-assistant/runs/${encodeURIComponent(runUid)}/tasks/${encodeURIComponent(taskUid)}`, { completed }, config)
}
