const API_ROOT = '/api/portal/v1'

export class PortalError extends Error {
  constructor(code, message, { status = 0, traceId = null, issues = [], uncertain = false } = {}) {
    super(message)
    this.name = 'PortalError'
    Object.assign(this, { code, status, traceId, issues, uncertain })
  }
}

function stale(uncertain = false) {
  return new PortalError('STALE_SCOPE', 'Your session changed. Please reload this page.', { uncertain })
}

function segment(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
    throw new PortalError('INVALID_INPUT', 'A valid resource identifier is required.')
  }
  return value
}

function versionHeader(version) {
  // Keep the server's BIGINT version as a string rather than rounding it in JS.
  const value = String(version)
  if (!/^[1-9][0-9]{0,18}$/.test(value) || (typeof version === 'number' && !Number.isSafeInteger(version))) {
    throw new PortalError('INVALID_INPUT', 'Refresh this page before continuing.')
  }
  return { 'If-Match': `"${value}"` }
}

/** One browser session boundary. No credentials or customer payloads are persisted. */
export function createPortalClient({ fetchImpl = globalThis.fetch.bind(globalThis), channel = null } = {}) {
  let epoch = 0
  let session = null
  let csrf = null
  let preauth = null
  let disposed = false
  let authBusy = false
  let pendingLogout = null
  const pending = new Set()
  const listeners = new Set()

  function emit(reason) {
    for (const listener of listeners) listener({ session, reason, epoch })
  }

  function clear(reason, broadcast = false) {
    epoch += 1
    session = null
    csrf = null
    preauth = null
    pendingLogout = null
    for (const controller of pending) controller.abort()
    pending.clear()
    emit(reason)
    if (broadcast) channel?.postMessage({ type: 'portal-session-changed' })
  }

  function received(event) {
    if (event.data?.type === 'portal-session-changed') clear('another-tab')
  }
  channel?.addEventListener('message', received)

  async function request(path, { method = 'GET', body, headers = {}, auth = 'session', signal, pdf = false, csrfToken } = {}) {
    if (disposed) throw new PortalError('CLIENT_CLOSED', 'This page is no longer active.')
    if (auth === 'session' && !session) throw new PortalError('SESSION_REQUIRED', 'Please sign in to continue.', { status: 401 })
    const token = csrfToken ?? (auth === 'preauth' ? preauth : csrf)
    if (method !== 'GET' && !token) throw new PortalError('CSRF_REQUIRED', 'Please refresh your session before continuing.')
    const started = epoch
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (signal?.aborted) abort()
    else signal?.addEventListener('abort', abort, { once: true })
    pending.add(controller)
    let dispatched = false
    const assertCurrent = () => {
      if (epoch !== started || disposed) throw stale(dispatched && method !== 'GET')
      if (controller.signal.aborted) throw new PortalError('REQUEST_ABORTED', 'The request was cancelled.', { uncertain: dispatched && method !== 'GET' })
    }
    try {
      assertCurrent()
      dispatched = true
      const response = await fetchImpl(`${API_ROOT}${path}`, {
        method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer', signal: controller.signal,
        headers: { Accept: pdf ? 'application/pdf' : 'application/json', ...headers,
          ...(method !== 'GET' ? { 'Content-Type': 'application/json', 'X-Portal-CSRF': token } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
      assertCurrent()
      // Revoke local data based on status even if a proxy replaces the JSON body.
      if (response.status === 401 && auth !== 'preauth') {
        clear('expired', true)
        throw new PortalError('SESSION_EXPIRED', 'Please sign in to continue.', { status: 401 })
      }
      if (response.ok && pdf) {
        if (response.headers.get('content-type')?.split(';')[0] !== 'application/pdf') {
          throw new PortalError('INVALID_RESPONSE', 'The document could not be downloaded.')
        }
        const blob = await response.blob()
        assertCurrent()
        return blob
      }
      let envelope
      try { envelope = await response.json() } catch {
        assertCurrent()
        throw new PortalError('INVALID_RESPONSE', 'The service returned an unreadable response.', { status: response.status, uncertain: method !== 'GET' })
      }
      assertCurrent()
      if (!response.ok) {
        const error = new PortalError(envelope?.data?.error_code || 'REQUEST_FAILED',
          envelope?.message || 'The request could not be completed.', {
            status: response.status, traceId: envelope?.data?.trace_id,
            issues: Array.isArray(envelope?.data?.issues) ? envelope.data.issues : [],
            uncertain: method !== 'GET' && response.status >= 500,
          })
        throw error
      }
      if (!envelope || typeof envelope !== 'object' || !Object.hasOwn(envelope, 'data') ||
          !Number.isInteger(envelope.code) || envelope.code < 200 || envelope.code >= 300) {
        throw new PortalError('INVALID_RESPONSE', 'The service returned an unreadable response.', { uncertain: method !== 'GET' })
      }
      return envelope.data
    } catch (error) {
      if (error instanceof PortalError) throw error
      if (epoch !== started || disposed) throw stale(dispatched && method !== 'GET')
      if (controller.signal.aborted) throw new PortalError('REQUEST_ABORTED', 'The request was cancelled.', { uncertain: dispatched && method !== 'GET' })
      throw new PortalError('NETWORK_ERROR', 'Connection interrupted. Please check the result before trying again.', { uncertain: method !== 'GET' })
    } finally {
      pending.delete(controller)
      signal?.removeEventListener('abort', abort)
    }
  }

  function acceptSession(data) {
    if (!data?.me?.account_public_id || !data.capabilities || typeof data.csrf_token !== 'string' || !data.csrf_token) {
      clear('invalid-session')
      throw new PortalError('INVALID_RESPONSE', 'Your session could not be verified.')
    }
    csrf = data.csrf_token
    preauth = null
    session = Object.freeze({ me: Object.freeze({ ...data.me }), capabilities: Object.freeze({ ...data.capabilities }) })
    emit('authenticated')
    return session
  }

  function query(values = {}) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(values)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    }
    return params.size ? `?${params}` : ''
  }

  async function authentication(operation) {
    if (authBusy) throw new PortalError('AUTH_BUSY', 'Please wait for the current sign-in operation.')
    authBusy = true
    try { return await operation() } finally { authBusy = false }
  }

  function ensureEpoch(started) { if (started !== epoch || disposed) throw stale() }

  return {
    get session() { return session },
    get scopeVersion() { return epoch },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    restore: () => authentication(async () => {
      clear('restoring')
      const started = epoch
      const data = await request('/session', { auth: 'restore' })
      ensureEpoch(started)
      return acceptSession(data)
    }),
    bootstrap: () => authentication(async () => {
      clear('signing-in', true)
      const started = epoch
      const data = await request('/auth/bootstrap', { auth: 'preauth' })
      ensureEpoch(started)
      if (typeof data?.csrf_token !== 'string' || !data.csrf_token) throw new PortalError('INVALID_RESPONSE', 'Sign-in is unavailable. Please try again.')
      preauth = data.csrf_token
      return { expires_in: data.expires_in }
    }),
    challenge({ email, invitationToken }) {
      return authentication(() => request('/auth/challenges', { auth: 'preauth', method: 'POST', body: {
        email, purpose: invitationToken ? 'activate' : 'login',
        ...(invitationToken ? { invitation_token: invitationToken } : {}),
      } }))
    },
    verify: (challengeId, code) => authentication(async () => {
      const started = epoch
      const data = await request('/auth/verify', { auth: 'preauth', method: 'POST', body: { challenge_id: segment(challengeId), code } })
      ensureEpoch(started)
      // Invalidate other pending authentication operations before installing this identity.
      clear('identity-changed', true)
      return acceptSession(data)
    }),
    logout: () => authentication(async () => {
      const token = csrf ?? (pendingLogout?.epoch === epoch ? pendingLogout.token : null)
      if (!token) throw new PortalError('SESSION_REQUIRED', 'There is no verified session to sign out.')
      // Abort private reads and clear their scope BEFORE the sign-out round trip.
      clear('signing-out', true)
      const started = epoch
      pendingLogout = { token, epoch: started }
      const result = await request('/auth/logout', { auth: 'logout', csrfToken: token, method: 'POST', body: {} })
      ensureEpoch(started)
      pendingLogout = null
      return result
    }),
    salesContact: signal => request('/sales-contact', { signal }),
    catalog: (filters, signal) => request(`/catalog${query(filters)}`, { signal }),
    product: (id, signal) => request(`/catalog/${segment(id)}`, { signal }),
    quote: body => request('/quotes', { method: 'POST', body }),
    quoteDetail: id => request(`/quotes/${segment(id)}`),
    submit: (key, body) => request('/orders', { method: 'POST', body, headers: { 'Idempotency-Key': segment(key) } }),
    orderByKey: key => request(`/orders/by-key/${segment(key)}`),
    orders: (filters, signal) => request(`/orders${query(filters)}`, { signal }),
    order: (id, signal) => request(`/orders/${segment(id)}`, { signal }),
    actionReceipt: (id, locator) => request(`/orders/${segment(id)}/action-receipt${query(locator)}`),
    cancel: (id, version, reason) => request(`/orders/${segment(id)}/cancel`, { method: 'POST', body: { reason }, headers: versionHeader(version) }),
    decide: (id, revision, version, decision, value) => {
      if (!['accept', 'reject'].includes(decision)) throw new PortalError('INVALID_INPUT', 'Choose a valid action.')
      return request(`/orders/${segment(id)}/proposals/${segment(revision)}/${decision}`, {
        method: 'POST', body: decision === 'accept' ? { proposal_hash: value } : { reason: value }, headers: versionHeader(version),
      })
    },
    reorder: (id, lineKeys, signal) => request(`/orders/${segment(id)}/reorder-quote`, { method: 'POST', body: lineKeys ? { line_keys: lineKeys } : {}, signal }),
    download: (id, signal) => request(`/orders/${segment(id)}/pi`, { pdf: true, signal }),
    dispose() {
      clear('disposed')
      disposed = true
      channel?.removeEventListener('message', received)
      channel?.close()
      listeners.clear()
    },
  }
}
