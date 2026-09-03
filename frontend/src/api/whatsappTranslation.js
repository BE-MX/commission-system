import { whatsappTranslationClient } from './clients'

export function inspectPairing(deviceCode) {
  return whatsappTranslationClient.post('/pairings/inspect', { device_code: deviceCode })
}

export function approvePairing(deviceCode) {
  return whatsappTranslationClient.post('/pairings/approve', { device_code: deviceCode })
}

export function rejectPairing(deviceCode) {
  return whatsappTranslationClient.post('/pairings/reject', { device_code: deviceCode })
}

export function getMyDevices() {
  return whatsappTranslationClient.get('/devices/me')
}

export function revokeMyDevice(deviceId) {
  return whatsappTranslationClient.delete(`/devices/me/${deviceId}`)
}

export function getMyUsage() {
  return whatsappTranslationClient.get('/usage/me')
}

export function getAdminDevices() {
  return whatsappTranslationClient.get('/admin/devices')
}

export function getAdminUsage() {
  return whatsappTranslationClient.get('/admin/usage')
}

export function getAdminHealth() {
  return whatsappTranslationClient.get('/admin/health')
}

export function revokeAdminDevice(deviceId) {
  return whatsappTranslationClient.delete(`/admin/devices/${deviceId}`)
}
