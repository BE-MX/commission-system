import test from 'node:test'
import assert from 'node:assert/strict'
import { nextDraftAmount, projectReceiptBalance, receiptActionState, invoiceOrderSignature, applySubmittedReceipt } from '../src/views/invoice/composables/invoiceReceiptState.js'
import { readFileSync } from 'node:fs'

test('saved drafts follow equal prepayments across decimal representations; manual amounts stay', () => {
  assert.equal(nextDraftAmount({ amount: '500.00', status: 'draft' }, 500, 650, 'stock'), 650)
  assert.equal(nextDraftAmount({ amount: 450, status: 'draft' }, 500, 650, 'stock'), 450)
  assert.equal(nextDraftAmount({ amount: 500, status: 'converted' }, 500, 650, 'stock'), 500)
  assert.equal(nextDraftAmount({ amount: 500, status: 'draft' }, 500, 650, 'presale'), 500)
})

test('increased and decreased totals show unpaid/overpaid without changing money', () => {
  const balance = { effective_amount: '1000', pending_amount: '200', registered_amount: '1200' }
  assert.deepEqual(projectReceiptBalance(balance, 1400), { unpaid: 400, overpaid: 0, available: 200, pendingExcess: 0 })
  assert.deepEqual(projectReceiptBalance(balance, 800), { unpaid: 0, overpaid: 200, available: 0, pendingExcess: 200 })
  assert.equal(balance.effective_amount, '1000')
})

test('converted local receipt actions depend on receipt state and remote identity', () => {
  assert.equal(receiptActionState({ status: 'active', sync_status: 'pending' }).editable, true)
  assert.equal(receiptActionState({ status: 'active', sync_status: 'failed', xiaoman_receipt_id: '88' }).editable, false)
  for (const sync_status of ['synced', 'syncing', 'uncertain']) {
    assert.equal(receiptActionState({ status: 'active', sync_status }).editable, false)
  }
  assert.equal(receiptActionState({ status: 'active', sync_status: 'failed', batch_id: 1 }).editable, false)
  assert.equal(receiptActionState({ status: 'active', sync_status: 'pending', purpose: 'presale_deposit' }).editable, false)
  assert.equal(receiptActionState({ status: 'voided', sync_status: 'pending' }).editable, false)
})

test('receipt refresh never marks unrelated order edits as saved', () => {
  const base = { items: [{ quantity: 1 }], remark: 'old', receipt_draft: { amount: 500 } }
  assert.equal(invoiceOrderSignature(base), invoiceOrderSignature({ ...base, receipt_draft: { amount: 600 } }))
  assert.notEqual(invoiceOrderSignature(base), invoiceOrderSignature({ ...base, remark: 'new' }))
})

test('generation refresh moves a ready intent to its authoritative receipt without touching order edits', () => {
  const form = { id: 1, remark: 'unsaved order note', receipt_draft: { status: 'ready', amount: 500 } }
  const row = { id: 11, invoice_id: 1, source: 'auto', amount: '600', version: 2, status: 'active', sync_status: 'failed', attachments: [{ id: 'replacement' }] }
  assert.equal(applySubmittedReceipt(form, row), true)
  assert.equal(form.receipt_draft.status, 'converted')
  assert.equal(form.receipt_draft.amount, 600)
  assert.equal(form.receipt_draft.receipt_version, 2)
  assert.deepEqual(form.receipt_draft.attachment_ids, ['replacement'])
  assert.equal(form.remark, 'unsaved order note')
  form.receipt_draft.status = 'draft'
  assert.equal(applySubmittedReceipt(form, { ...row, amount: '900' }), false)
  assert.equal(form.receipt_draft.amount, 600)
})

test('auto corrections submit zero fee for server allocation, including reductions below the old fee', () => {
  const dialog = readFileSync(new URL('../src/views/invoice/components/InvoiceReceiptPaymentDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /bank_charge: props\.receipt\?\.source === 'auto' \? '0'/)
})
