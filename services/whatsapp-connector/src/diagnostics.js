import { createHash } from 'node:crypto'

const time = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit',
  day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
const events = new Set(['authorization_failed', 'socket_start', 'companion_reg_refresh', 'qr_ready',
  'pairing_credentials', 'connection_open', 'connection_closed', 'protected_pause'])
const classifications = new Set(['reauth_required', 'blocked', 'restart', 'transient', 'protected_pause'])
const reasons = new Set(['authorization_unavailable', 'authorization_denied', 'authorization_changed',
  'reauth_required', 'blocked', 'protected_pause', 'reconnect_exhausted', 'auth_store_failed', 'auth_cas_conflict',
  'connection_update_failed', 'event_store_failed', 'socket_start_failed', 'backpressure_gap', 'disk_capacity',
  'collection_paused', 'invalid_event', 'stale_lease', 'stale_generation', 'stale_consent'])
const transports = new Set(['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN',
  'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT', 'UND_ERR_SOCKET'])
const choice = (value, allowed) => allowed.has(value) ? value : 'other'
const status = value => Number.isInteger(value) && value >= 100 && value <= 599 ? value : null

// Never serialize the caller's object, error, protocol stanza, URL or credentials.
export function createDiagnostics(write = line => console.info(line), now = Date.now) {
  return (event, uid, detail = {}) => {
    if (!events.has(event)) return
    try {
      const value = { source: 'whatsapp_connector', at: `${time.format(new Date(now())).replace(' ', 'T')}+08:00`,
        event, account: createHash('sha256').update(String(uid)).digest('hex').slice(0, 16) }
      if (event === 'authorization_failed') Object.assign(value, {
        phase: choice(detail.phase, new Set(['request', 'response', 'validation'])),
        failure: choice(detail.failure, new Set(['timeout', 'transport', 'http_error', 'invalid_response', 'denied'])),
        http_status: status(detail.http_status), transport_code: choice(detail.transport_code, transports),
        elapsed_ms: Number.isFinite(detail.elapsed_ms) ? Math.max(0, Math.round(detail.elapsed_ms)) : null,
      })
      if (['socket_start', 'pairing_credentials', 'connection_open', 'connection_closed', 'companion_reg_refresh'].includes(event)) {
        value.registered = detail.registered === true
        value.has_identity = detail.has_identity === true
      }
      if (event === 'connection_closed') Object.assign(value, {
        status_code: status(detail.status_code), classification: choice(detail.classification, classifications),
      })
      if (event === 'protected_pause') value.reason = choice(detail.reason, reasons)
      write(JSON.stringify(value))
    } catch { console.warn('connector_diagnostic_output_failed') }
  }
}

export const diagnostic = createDiagnostics()
