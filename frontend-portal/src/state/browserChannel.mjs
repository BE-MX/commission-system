/** Invalidation only; no identity, credentials or customer data cross this channel. */
export function browserChannel(browser = window, onUnavailable = () => {}) {
  if (browser.BroadcastChannel) {
    try { return new browser.BroadcastChannel('leshine-portal-session') }
    catch { /* Sandboxed browsers can expose the constructor but deny access. */ }
  }
  const listeners = new Set()
  const key = 'leshine.portal.session-change'
  const handler = event => {
    if (event.key === key && event.newValue) {
      for (const listener of listeners) listener({ data: { type: 'portal-session-changed' } })
    }
  }
  browser.addEventListener('storage', handler)
  return {
    addEventListener(type, listener) { if (type === 'message') listeners.add(listener) },
    removeEventListener(type, listener) { if (type === 'message') listeners.delete(listener) },
    postMessage() {
      // Failure is surfaced to the app; it must not claim synchronized sign-out.
      try { browser.localStorage.setItem(key, browser.crypto.randomUUID()) }
      catch { onUnavailable() }
    },
    close() { browser.removeEventListener('storage', handler); listeners.clear() },
  }
}
