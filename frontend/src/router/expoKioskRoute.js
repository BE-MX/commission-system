import { readSessionItem, writeSessionItem } from '../utils/safeSessionStorage.js'

export const EXPO_KIOSK_PATH = '/expo/kiosk'
export const EXPO_KIOSK_LOCK_KEY = 'ark_expo_kiosk_mode'
let inMemoryKioskMode = false

function normalisePath(path) {
  const value = String(path || '').toLowerCase().replace(/\/+$/, '')
  return value || '/'
}

export function isExpoKioskTarget(route) {
  if (String(route?.name || '') === 'ExpoKiosk') return true
  if (route?.matched?.some(record => String(record?.name || '') === 'ExpoKiosk')) return true
  return normalisePath(route?.path) === EXPO_KIOSK_PATH
}

function isLoginTarget(route) {
  return String(route?.name || '') === 'Login' || normalisePath(route?.path) === '/login'
}

export function enterExpoKioskMode(storage) {
  inMemoryKioskMode = true
  writeSessionItem(EXPO_KIOSK_LOCK_KEY, '1', storage)
}

export function isExpoKioskMode(storage) {
  if (inMemoryKioskMode) return true
  return readSessionItem(EXPO_KIOSK_LOCK_KEY, storage) === '1'
}

export function expoKioskLoginLocation(query = {}) {
  return {
    name: 'Login',
    query: { ...query, redirect: EXPO_KIOSK_PATH },
    replace: true,
  }
}

/**
 * 展会设备一旦进入 kiosk，该浏览器标签页就不再允许进入方舟后台。
 * sessionStorage 随标签页关闭自动释放；登录页仅用于重新认证，并强制回 kiosk。
 */
export function guardExpoKioskBoundary(to, storage) {
  const kioskTarget = isExpoKioskTarget(to)
  if (kioskTarget) enterExpoKioskMode(storage)
  if (!isExpoKioskMode(storage)) return null

  if (isLoginTarget(to)) {
    if (String(to?.query?.redirect || '') === EXPO_KIOSK_PATH) return null
    return expoKioskLoginLocation(to?.query)
  }
  if (!kioskTarget) {
    return { name: 'ExpoKiosk', replace: true }
  }
  return null
}
