import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { invoiceReceiptSyncGuidance } from '../src/views/invoice/composables/invoiceReceiptState.js'

// Execute the actual editor handler with isolated API/UI dependencies.
const source = readFileSync(new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url), 'utf8')
const handler = source.slice(source.indexOf('  async function saveAndSync() {'), source.indexOf('  function showIssues('))
const outcomes = { SUCCESS: 'success', FAILED: 'failed', DUPLICATE: 'duplicate', CANCELLED: 'cancelled' }
function fixture({ dirty = false, groups = false, outcome = 'success', remoteStatus = 'synced', readFails = false } = {}) {
  const calls = [], warnings = []
  const form = { id: 1916, order_type: 'stock', sync_status: 'not_synced', xiaoman_order_id: 'existing',
    receipt_draft: { eligible: false, amount: 0, status: 'draft' } }
  const hasUnsavedChanges = { value: dirty }, submitting = { value: false }
  const dependencies = { form, invoiceIsLocal: () => false, msgWarning: message => warnings.push(message),
    saveAndSyncSubmitting: submitting, hasOnlyGroupChanges: () => groups, hasUnsavedChanges,
    confirmAction: async () => calls.push('confirm'), isFeedbackCancelled: error => error === 'cancel',
    saveDraft: async options => { calls.push(['save', options.linked]); hasUnsavedChanges.value = false; return { ...form } },
    lastSaveType: { value: groups ? 'groups' : 'business' }, msgSuccessText: () => calls.push('no-sync'),
    linked: { run: async () => { calls.push('linked'); return { status: 'done' } } },
    showSyncCompletion: () => calls.push('complete'), showIssues: () => {},
    validateThenSync: async id => { calls.push(['sync', id]); return outcome }, INVOICE_SYNC_OUTCOME: outcomes,
    onSaved: () => calls.push('list'), getInvoice: async () => {
      calls.push('read'); if (readFails) throw new Error('Read failed')
      return { ...form, sync_status: remoteStatus }
    }, resetForm: current => Object.assign(form, current), drawerVisible: { value: true }, legacyVisible: { value: false } }
  const run = () => new Function(...Object.keys(dependencies), `let pendingLinkedCompletion; ${handler}; return saveAndSync()`)(...Object.values(dependencies))
  return { form, calls, warnings, dependencies, run }
}

test('already saved unsynced invoice syncs directly without an identical linked save', async () => {
  const f = fixture()
  await f.run()
  assert.deepEqual(f.calls, [['sync', 1916], 'list', 'read', 'complete'])
  assert.equal(f.form.sync_status, 'synced')
})

test('saving only groups still syncs outstanding saved business changes', async () => {
  const f = fixture({ dirty: true, groups: true })
  await f.run()
  assert.deepEqual(f.calls, [['save', false], ['sync', 1916], 'list', 'read', 'complete'])
})

test('unsaved business changes retain linked synchronization', async () => {
  const f = fixture({ dirty: true })
  await f.run()
  assert.deepEqual(f.calls, [['save', true], 'linked', 'complete'])
})

test('already synchronized clean invoices never push again from the shared footer', async () => {
  const f = fixture()
  f.form.sync_status = 'synced'
  await f.run()
  assert.deepEqual(f.calls, ['no-sync'])
})

test('uncertain results, linked tasks and blocked presale edits retain recovery guards', async () => {
  for (const patch of [{ sync_status: 'sync_uncertain' }, { linked_sync_id: 'existing' }, { presale_edit_blocked_reason: '先处理原批次' }]) {
    const f = fixture()
    Object.assign(f.form, patch)
    await f.run()
    assert.deepEqual(f.calls, [])
    assert.equal(f.warnings.length, 1)
  }
})

test('zero first-payment confirmation still precedes a saved first sync and cancellation makes no request', async () => {
  const f = fixture()
  f.form.receipt_draft.eligible = true
  f.dependencies.confirmAction = async () => { f.calls.push('confirm'); throw 'cancel' }
  await f.run()
  assert.deepEqual(f.calls, ['confirm'])
  assert.equal(f.dependencies.saveAndSyncSubmitting.value, false)
})

test('uncertain first sync refreshes the drawer and replaces retry with recovery guidance', async () => {
  const f = fixture({ outcome: 'failed', remoteStatus: 'sync_uncertain' })
  f.form.xiaoman_order_id = null
  await f.run()
  assert.equal(f.form.sync_status, 'sync_uncertain')
  assert.equal(invoiceReceiptSyncGuidance(f.form).canSync, false)
  assert.match(invoiceReceiptSyncGuidance(f.form).message, /处理待核对/)
  assert.ok(!f.calls.includes('complete'))
})

test('failed status read blocks another submission until the order is reopened', async () => {
  const f = fixture({ outcome: 'failed', readFails: true })
  await f.run()
  const before = [...f.calls]
  assert.equal(invoiceReceiptSyncGuidance(f.form).canSync, false)
  await f.run()
  assert.deepEqual(f.calls, before)
  assert.equal(f.dependencies.saveAndSyncSubmitting.value, false)
})

test('open receipt operations block even a clean saved invoice', async () => {
  const f = fixture()
  f.form.receipt_action_open = true
  await f.run()
  assert.deepEqual(f.calls, [])
  assert.match(f.warnings[0], /当前回款操作/)
})

test('edits made during sync survive authoritative status refresh', async () => {
  const f = fixture({ outcome: 'failed', remoteStatus: 'sync_uncertain' })
  f.dependencies.validateThenSync = async () => {
    f.form.remark = 'unsaved edit'
    f.dependencies.hasUnsavedChanges.value = true
    return 'failed'
  }
  f.dependencies.getInvoice = async () => ({ id: 1916, remark: 'saved remark', sync_status: 'sync_uncertain' })
  await f.run()
  assert.equal(f.form.remark, 'unsaved edit')
  assert.equal(f.form.sync_status, 'sync_uncertain')
})
