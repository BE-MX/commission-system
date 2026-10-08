import { PortalError } from '../api/client.mjs'
import { quoteDeadline } from './checkout.mjs'
import { actionRecovery, commandPayloadHash, queryLocator, normalizeReason } from './actionRecovery.mjs'

const pending = status => ['sending', 'checking', 'uncertain'].includes(status)
const requestStates = new Set(['submitted', 'awaiting_customer', 'ready_for_review', 'invoice_created', 'rejected', 'cancelled'])
const amendmentStates = new Set(['current', 'withdrawn', 'pending_customer', 'accepted'])
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
function integerVersion(value) {
  if (typeof value === 'number' && (!Number.isSafeInteger(value) || value <= 0)) return null
  if (!['number', 'string'].includes(typeof value) || !/^[1-9][0-9]{0,18}$/.test(String(value))) return null
  return BigInt(String(value))
}
function validReceipt(receipt, operation) {
  const original = receipt?.original_receipt
  const currentVersion = integerVersion(receipt?.row_version), originalVersion = integerVersion(original?.row_version)
  if (original?.request_id !== operation.request_id || !requestStates.has(receipt?.current_state)
    || currentVersion == null || originalVersion == null || currentVersion < originalVersion) return false
  if (operation.action === 'cancel') return original.status === 'cancelled'
  if (original.revision_id !== operation.revision_id || original.content_hash !== operation.proposal_hash) return false
  if (operation.action.endsWith('_pi')) {
    return integerVersion(original.invoice_document_version) === integerVersion(operation.invoice_document_version)
      && integerVersion(original.invoice_document_version) != null && amendmentStates.has(receipt.amendment_state)
  }
  return original.status === (operation.action.startsWith('accept') ? 'ready_for_review' : 'submitted')
}

export function currentProposal(order) {
  return order.status === 'invoice_created' ? order.pi_amendment?.proposal : order.proposal
}
/** A command keeps its original revision, hash, version and reason across manual retries. */
export function createOrderDecision({ api, storage = null, now = () => Date.now() }) {
  const recovery = actionRecovery(storage)
  function account() {
    const id = api.session?.me?.account_public_id
    if (storage && !uuid(id)) throw new PortalError('SESSION_REQUIRED', 'Please sign in to continue.')
    return id
  }
  function confirmed(receipt) {
    recovery.forget(operation.account, operation.marker)
    return update({ status: 'confirmed', operation, receipt })
  }
  async function checkReceipt(started) {
    update({ status: 'checking', operation, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted })
    try {
      const locator = queryLocator(operation)
      const result = await api.actionReceipt(operation.request_id, locator)
      current(started, true)
      const command = result?.command
      if (typeof result?.found !== 'boolean' || command?.request_id !== operation.request_id
        || Object.keys(locator).some(key => command?.[key] !== locator[key])
        || Object.keys(command).length !== Object.keys(locator).length + 1) throw new PortalError('INVALID_RESPONSE', 'The original action receipt could not be verified.')
      if (!result.found) return check(started)
      if (!validReceipt(result.receipt, operation)) throw new PortalError('INVALID_RESPONSE', 'The original action receipt could not be verified.')
      return confirmed(result.receipt)
    } catch (error) { current(started, true); return update({ status: 'uncertain', operation, error, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted }) }
  }
  let generation = 0, operation = null
  let state = Object.freeze({ status: 'idle' })
  const listeners = new Set()
  function update(value) { state = Object.freeze(value); for (const listener of listeners) listener(state); return state }
  function current(started, uncertain = false) { if (started !== generation) throw new PortalError('STALE_SCOPE', 'Your session changed.', { uncertain }) }
  const offSession = api.subscribe(({ reason }) => {
    if (reason !== 'authenticated') { generation++; operation = null; update({ status: 'idle' }) }
  })
  async function check(started) {
    update({ status: 'checking', operation, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted })
    try {
      const latest = await api.order(operation.request_id)
      current(started, true)
      if (latest?.request_id !== operation.request_id || !requestStates.has(latest?.status) || integerVersion(latest?.row_version) == null) {
        throw new PortalError('INVALID_RESPONSE', 'The original request status could not be verified.')
      }
      // A state read is not a command receipt: another buyer may have changed this order.
      return update({ status: 'uncertain', operation, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted, latest })
    } catch (error) { current(started, true); return update({ status: 'uncertain', operation, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted, error }) }
  }
  async function send(started, retry = false) {
    update({ status: 'sending', operation, canRetry: operation.value !== undefined, refreshRecovery: operation.persisted })
    try {
      const receipt = operation.action === 'cancel'
        ? await api.cancel(operation.request_id, operation.version, operation.value)
        : await api.decide(operation.request_id, operation.revision_id, operation.version, operation.action.startsWith('accept') ? 'accept' : 'reject', operation.value)
      current(started, true)
      if (!validReceipt(receipt, operation)) {
        throw new PortalError('INVALID_RESPONSE', 'The action result could not be verified.', { uncertain: true })
      }
      return confirmed(receipt)
    } catch (error) {
      current(started, true)
      if (error.uncertain || retry) return check(started)
      recovery.forget(operation.account, operation.marker)
      return update({ status: 'failed', operation, error })
    }
  }
  async function prepare(started) {
    update({ status: 'sending', operation, canRetry: false, refreshRecovery: false })
    try {
      const payload_hash = await commandPayloadHash(operation.action, operation.value)
      current(started)
      const prepared = { ...operation, payload_hash }
      operation = Object.freeze({ ...prepared, ...recovery.remember(operation.account, prepared) })
    } catch (error) {
      current(started)
      return update({ status: 'failed', operation, error })
    }
    return send(started)
  }
  return {
    get state() { return state },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    begin(order, action, reason = '') {
      if (pending(state.status)) throw new PortalError('ACTION_PENDING', 'Resolve the previous action before sending another.')
      if (!api.session?.capabilities?.place_order || !order.available_actions?.includes(action) || !['cancel', 'accept_proposal', 'reject_proposal', 'accept_pi', 'reject_pi'].includes(action)) {
        throw new PortalError('ACTION_UNAVAILABLE', 'Refresh this request to check available actions.')
      }
      if (!uuid(order.request_id) || integerVersion(order.row_version) == null) throw new PortalError('INVALID_RESPONSE', 'Refresh this request before continuing.')
      const buyer = account()
      if (recovery.read(buyer)) throw new PortalError('ACTION_PENDING', 'Recover the previous action before sending another.')
      const proposal = currentProposal(order)
      const accept = action.startsWith('accept')
      if (action.endsWith('_pi') && integerVersion(proposal?.bound_invoice_document_version) == null) throw new PortalError('PROPOSAL_UNAVAILABLE', 'Refresh this PI proposal before continuing.')
      if (action !== 'cancel' && (!uuid(proposal?.revision_id) || !hash(proposal?.content_hash))) throw new PortalError('PROPOSAL_UNAVAILABLE', 'Refresh this proposal before continuing.')
      if (accept && (proposal.expired || !(quoteDeadline(proposal.expires_at) > now()))) throw new PortalError('PROPOSAL_EXPIRED', 'This proposal has expired or changed. Refresh the request.')
      const normalizedReason = normalizeReason(reason)
      if (!accept && (typeof reason !== 'string' || !normalizedReason || normalizedReason.length > 500)) throw new PortalError('REASON_REQUIRED', 'Enter a reason, up to 500 characters.')
      operation = Object.freeze({ account: buyer, request_id: order.request_id, request_no: order.request_no, action,
        version: order.row_version, revision_id: action === 'cancel' ? undefined : proposal.revision_id,
        proposal_hash: action === 'cancel' ? undefined : proposal.content_hash,
        invoice_document_version: action.endsWith('_pi') ? proposal.bound_invoice_document_version : undefined,
        value: accept ? proposal.content_hash : normalizedReason })
      return prepare(generation)
    },
    restorePending() {
      if (state.status !== 'idle') throw new PortalError('ACTION_PENDING', 'An action is already in progress.')
      const buyer = account(), saved = recovery.read(buyer)
      if (!saved) return false
      operation = Object.freeze({ ...saved, account: buyer, persisted: true })
      update({ status: 'uncertain', operation, canRetry: false, refreshRecovery: true })
      return true
    },
    recover() {
      if (state.status !== 'uncertain') throw new PortalError('ACTION_UNAVAILABLE', 'There is no action to check.')
      return checkReceipt(generation)
    },
    retry() {
      if (state.status !== 'uncertain' || !operation || operation.value === undefined) throw new PortalError('ACTION_UNAVAILABLE', 'There is no original action to retry.')
      return send(generation, true)
    },
    dismiss() {
      if (pending(state.status)) throw new PortalError('ACTION_PENDING', 'Confirm the previous action first.')
      operation = null; update({ status: 'idle' })
    },
    dispose() { generation++; operation = null; offSession(); listeners.clear(); state = Object.freeze({ status: 'idle' }) },
  }
}
