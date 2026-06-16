import { whatsappClient } from './clients'

export function listWhatsAppAccounts() {
  return whatsappClient.get('/accounts')
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

export function listWhatsAppConversations(params) {
  return whatsappClient.get('/conversations', { params })
}

export function listWhatsAppMessages(params) {
  return whatsappClient.get('/messages', { params })
}
