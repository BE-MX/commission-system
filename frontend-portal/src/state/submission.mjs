import { PortalError } from '../api/client.mjs'

const STORAGE_PREFIX = 'leshine.portal.pending:'

/** A single immutable checkout operation; retries always reuse the original key/body. */
export function createSubmission({ api, storage = null, newKey = () => crypto.randomUUID() }) {
  let generation = 0
  let operation = null
  let state = Object.freeze({ status: 'idle' })
  const listeners = new Set()
  const unsubscribe = api.subscribe(({ reason }) => {
    if (reason !== 'authenticated') {
      generation += 1
      operation = null
      update({ status: 'idle' })
    }
  })

  function update(value) {
    state = Object.freeze(value)
    for (const listener of listeners) listener(state)
    return state
  }

  function account() {
    const id = api.session?.me?.account_public_id
    if (!id) throw new PortalError('SESSION_REQUIRED', 'Please sign in to continue.')
    return id
  }

  function assertCurrent(started, uncertain = false) {
    if (started !== generation) throw new PortalError('STALE_SCOPE', 'Your session changed. Please reload this page.', { uncertain })
  }

  function remember() {
    try {
      operation.marker = JSON.stringify({ key: operation.key })
      storage?.setItem(STORAGE_PREFIX + operation.account, operation.marker)
      return Boolean(storage) && storage.getItem(STORAGE_PREFIX + operation.account) === operation.marker
    } catch { return false } // Storage restrictions affect refresh recovery, not server authorization.
  }

  function forget() {
    try {
      const saved = savedOperation(operation.account)
      // A late response owns only its original marker, never a replacement.
      if (saved?.key === operation.key && saved.marker === operation.marker) storage.removeItem(STORAGE_PREFIX + operation.account)
    } catch { /* Preserve unreadable/corrupt markers; the next begin will refuse them. */ }
  }

  function savedOperation(buyer) {
    if (!storage) return null
    let raw
    try { raw = storage.getItem(STORAGE_PREFIX + buyer) }
    catch {
      throw new PortalError('RECOVERY_STORAGE_UNAVAILABLE', 'This browser could not read your previous request reference. Try again or contact your representative before placing another request.')
    }
    if (raw == null) return null
    let saved
    try { saved = JSON.parse(raw) } catch { /* Validate below without exposing storage contents. */ }
    if (!saved || typeof saved !== 'object' || Array.isArray(saved) || Object.keys(saved).length !== 1
      || typeof saved.key !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(saved.key)) {
      throw new PortalError('RECOVERY_RECORD_INVALID', 'Your previous request reference could not be verified. Contact your representative to review the original request before placing another one.')
    }
    return { key: saved.key, marker: raw }
  }

  function confirmed(receipt) {
    if (!receipt?.request_id || !receipt.request_no) throw new PortalError('INVALID_RESPONSE', 'The order result could not be verified.', { uncertain: true })
    forget()
    return update({ status: 'confirmed', receipt })
  }

  async function check(started) {
    update({ status: 'checking', key: operation.key, refreshRecovery: operation.persisted })
    try {
      const receipt = await api.orderByKey(operation.key)
      assertCurrent(started)
      return confirmed(receipt)
    } catch (error) {
      assertCurrent(started)
      // A 404 may race an in-flight commit. It never authorizes a new checkout key.
      return update({ status: 'uncertain', key: operation.key, error,
        canRetry: Boolean(operation.body), refreshRecovery: operation.persisted })
    }
  }

  async function send(started, retry = false) {
    update({ status: 'submitting', key: operation.key, refreshRecovery: operation.persisted })
    try {
      const receipt = await api.submit(operation.key, operation.body)
      assertCurrent(started, true)
      return confirmed(receipt)
    } catch (error) {
      assertCurrent(started, true)
      if (error.uncertain || retry) return check(started)
      forget()
      return update({ status: 'failed', error })
    }
  }

  return {
    get state() { return state },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    begin({ quote_id, quote_content_hash, customer_po = '', remark = '' }) {
      if (!['idle', 'failed', 'confirmed'].includes(state.status)) throw new PortalError('SUBMISSION_PENDING', 'Please confirm the result of your previous request first.')
      const buyer = account()
      if (savedOperation(buyer)) throw new PortalError('SUBMISSION_PENDING', 'Recover the previous request before submitting another one.')
      // Construct a fresh body rather than retaining a mutable cart/form reference.
      if (typeof quote_id !== 'string' || typeof quote_content_hash !== 'string' || typeof customer_po !== 'string' || typeof remark !== 'string') {
        throw new PortalError('INVALID_INPUT', 'Please refresh your quote before submitting.')
      }
      operation = { account: buyer, key: newKey(), body: Object.freeze({ quote_id, quote_content_hash, customer_po, remark }) }
      operation.persisted = remember()
      return send(generation)
    },
    restorePending() {
      if (state.status !== 'idle') throw new PortalError('SUBMISSION_PENDING', 'A request is already in progress.')
      const buyer = account()
      const saved = savedOperation(buyer)
      if (!saved) return false
      operation = { account: buyer, key: saved.key, body: null, marker: saved.marker, persisted: true }
      update({ status: 'uncertain', key: saved.key, canRetry: false, refreshRecovery: true })
      return true
    },
    recover() {
      account()
      if (state.status !== 'uncertain') throw new PortalError('INVALID_ACTION', 'There is no pending result to check.')
      return check(generation)
    },
    retry() {
      account()
      if (state.status !== 'uncertain' || !operation?.body) throw new PortalError('INVALID_ACTION', 'Check the original request result before continuing.')
      return send(generation, true)
    },
    dispose() { unsubscribe(); generation += 1; operation = null; listeners.clear(); state = Object.freeze({ status: 'idle' }) },
  }
}
