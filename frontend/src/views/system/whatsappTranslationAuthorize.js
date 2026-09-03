const DEVICE_CODE_KEY = 'ark_whatsapp_translation_device_code'

export function readDeviceCode(location = { hash: '', search: '' }) {
  if (location.search?.includes('device_code=')) return ''
  if (!location.hash?.startsWith('#')) return ''
  const code = new URLSearchParams(location.hash.slice(1)).get('device_code')
  return code && /^[A-Za-z0-9_-]{8,128}$/.test(code) ? code : ''
}

export function cleanAuthorizeUrl(location = { pathname: '/whatsapp-translation/authorize' }) {
  return location.pathname || '/whatsapp-translation/authorize'
}

export function captureDeviceCode(location, history = globalThis.history, storage = globalThis.sessionStorage) {
  const code = readDeviceCode(location)
  if (!code) return ''
  writeCode(code, storage)
  history?.replaceState({}, '', cleanAuthorizeUrl(location))
  return code
}

export function clearDeviceCode(storage = globalThis.sessionStorage) {
  removeCode(storage)
}

function writeCode(code, storage) {
  try {
    storage?.setItem(DEVICE_CODE_KEY, code)
  } catch {
    // Storage failures do not create a URL or Referer fallback.
  }
}

function removeCode(storage) {
  try {
    storage?.removeItem(DEVICE_CODE_KEY)
  } catch {
    // Cleared when storage becomes available.
  }
}
