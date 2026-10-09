import { PortalError } from '../api/client.mjs'
export const actionNames = new Set(['cancel', 'accept_proposal', 'reject_proposal', 'accept_pi', 'reject_pi'])
const prefix = 'leshine.portal.action:'
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const version = value => typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value)
export function queryLocator(operation) {
  return { action: operation.action, payload_hash: operation.payload_hash,
    ...(operation.action === 'cancel' ? {} : { revision_id: operation.revision_id, proposal_hash: operation.proposal_hash }) }
}
// Normalize before freezing/sending. NEL is Unicode White_Space, absent from JS trim.
export const normalizeReason = value => typeof value === 'string' ? value.replace(/^[\s\u0085]+|[\s\u0085]+$/g, '') : ''
export async function commandPayloadHash(action, value) {
  // Match Python content_hash: UTF-8, sorted single-field payload, hash_schema=1.
  // Reject lone surrogates rather than allowing TextEncoder to replace original input.
  if (typeof value !== 'string' || [...value].some(char => { const point=char.codePointAt(0); return point >= 0xd800 && point <= 0xdfff })) {
    throw new PortalError('INVALID_INPUT', 'Please check the original action text.')
  }
  try {
    const payload = action.startsWith('accept') ? { proposal_hash: value } : { reason: value }
    const bytes = new TextEncoder().encode(JSON.stringify({ hash_schema: 1, payload }))
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
    return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
  } catch { throw new PortalError('RECOVERY_UNAVAILABLE', 'The original action reference could not be prepared. Please try again.') }
}
function markerFor(operation) {
  return { schema: 1, request_id: operation.request_id, action: operation.action, version: String(operation.version),
    payload_hash: operation.payload_hash, ...(operation.action === 'cancel' ? {} : { revision_id: operation.revision_id, proposal_hash: operation.proposal_hash }),
    ...(operation.action.endsWith('_pi') ? { invoice_document_version: String(operation.invoice_document_version) } : {}) }
}
export function actionRecovery(storage) {
  function read(account) {
    if (!storage) return null
    let raw
    try { raw = storage.getItem(prefix + account) }
    catch { throw new PortalError('RECOVERY_STORAGE_UNAVAILABLE', 'Your previous action reference could not be read. Try again or contact your representative before sending another action.') }
    if (raw == null) return null
    let saved
    try { saved = JSON.parse(raw) } catch { /* Only the safe fixed message is exposed. */ }
    const fields = ['schema', 'request_id', 'action', 'version', 'payload_hash', ...(saved?.action === 'cancel' ? [] : ['revision_id', 'proposal_hash']), ...(saved?.action?.endsWith?.('_pi') ? ['invoice_document_version'] : [])]
    if (!saved || Array.isArray(saved) || saved.schema !== 1 || !uuid(saved.request_id) || !actionNames.has(saved.action)
      || !version(saved.version) || !hash(saved.payload_hash) || Object.keys(saved).length !== fields.length || fields.some(key => !Object.hasOwn(saved, key))
      || (saved.action !== 'cancel' && (!uuid(saved.revision_id) || !hash(saved.proposal_hash)))
      || (saved.action.endsWith('_pi') && !version(saved.invoice_document_version))) {
      throw new PortalError('RECOVERY_RECORD_INVALID', 'Your previous action reference could not be verified. Contact your representative to review the original action before sending another.')
    }
    return { ...saved, marker: raw }
  }
  return { read,
    remember(account, operation) {
      // Recheck after async hashing; never replace a pending operation.
      if (read(account)) throw new PortalError('ACTION_PENDING', 'Recover the previous action before sending another.')
      if (!storage) return { persisted: false }
      const marker = JSON.stringify(markerFor(operation))
      try { storage.setItem(prefix + account, marker); return { marker, persisted: storage.getItem(prefix + account) === marker } }
      catch { return { marker, persisted: false } }
    },
    forget(account, marker) {
      try { if (marker && read(account)?.marker === marker) storage.removeItem(prefix + account) }
      catch { /* Preserve a corrupt, unreadable or replaced reference. */ }
    },
  }
}
