export const INVITE_KEY = 'ark_customer_image_invite'

function defaultStorage() {
  return globalThis.sessionStorage
}

export function captureInviteToken(token, {
  history = globalThis.history,
  storage = defaultStorage(),
} = {}) {
  const normalized = typeof token === 'string' ? token.trim() : ''
  if (!normalized) return false
  storage.setItem(INVITE_KEY, normalized)
  history.replaceState(history.state ?? null, '', '/create')
  return true
}

export function getInviteToken(storage = defaultStorage()) {
  const token = storage.getItem(INVITE_KEY)
  return token?.trim() || null
}

export function getInviteAuthorization(storage = defaultStorage()) {
  const token = getInviteToken(storage)
  return token ? `Invite ${token}` : null
}

export function clearInviteToken(storage = defaultStorage()) {
  storage.removeItem(INVITE_KEY)
}
