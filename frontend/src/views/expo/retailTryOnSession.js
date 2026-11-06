export const RETAIL_TRYON_PATH = '/expo/retail'
const GRANT_KEY = 'leshine_retail_tryon_grant'
const RETURN_KEY = 'leshine_retail_tryon_return'
const GRANT_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function isRetailTryOnPage(location = globalThis.location) {
  return location?.pathname?.replace(/\/+$/, '') === RETAIL_TRYON_PATH
}

function safeReturnUrl(value) {
  try {
    const parsed = new URL(value)
    const allowed = parsed.origin === 'https://leshine-wig-platform.pages.dev'
      || ['localhost', '127.0.0.1'].includes(parsed.hostname)
    return allowed && parsed.pathname.startsWith('/retail') ? parsed.href : ''
  } catch {
    return ''
  }
}

export function captureRetailTryOnSession({
  location = globalThis.location,
  history = globalThis.history,
  storage = globalThis.sessionStorage,
} = {}) {
  const params = new URLSearchParams(String(location?.hash || '').replace(/^#/, ''))
  const grant = String(params.get('grant') || '').trim()
  const returnUrl = safeReturnUrl(params.get('return') || '')
  if (GRANT_RE.test(grant)) storage.setItem(GRANT_KEY, grant)
  if (returnUrl) storage.setItem(RETURN_KEY, returnUrl)
  if (location?.hash) history.replaceState(history.state ?? null, '', RETAIL_TRYON_PATH)
  return GRANT_RE.test(storage.getItem(GRANT_KEY) || '')
}

export function getRetailTryOnAuthorization(storage = globalThis.sessionStorage) {
  const grant = storage.getItem(GRANT_KEY) || ''
  return GRANT_RE.test(grant) ? `Retail ${grant}` : null
}

export function getRetailTryOnReturnUrl(storage = globalThis.sessionStorage) {
  return safeReturnUrl(storage.getItem(RETURN_KEY) || '')
    || 'https://leshine-wig-platform.pages.dev/retail'
}
