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
