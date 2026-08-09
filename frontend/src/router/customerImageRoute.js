import { captureInviteToken } from '../views/customer-image/inviteSession.js'

export function captureCustomerImageRouteToken(token, capture = captureInviteToken) {
  if (!token) return true
  capture(String(token))
  return { name: 'CustomerImagePortal', replace: true }
}

export function bypassCustomerImageRoute(to, next, setTitle = () => {}) {
  if (!to.meta?.customerImage) return false
  setTitle(`${to.meta.title} - 莱莎方舟`)
  next()
  return true
}
