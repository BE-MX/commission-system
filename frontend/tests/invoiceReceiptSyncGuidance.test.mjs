import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { invoiceReceiptSyncGuidance } from '../src/views/invoice/composables/invoiceReceiptState.js'

const saved = { id: 1916, order_type: 'stock', sync_status: 'not_synced', xiaoman_order_id: 'existing-order',
  receipt_draft: { eligible: false, status: 'draft', amount: 0 } }

test('saved unsynced orders explain the next action, including failed resync and unsaved edits', () => {
  for (const form of [saved, { ...saved, sync_status: 'sync_failed' }, { ...saved, sync_status: 'synced', receipt_order_dirty: true }]) {
    const guidance = invoiceReceiptSyncGuidance(form)
    assert.match(guidance.message, /先保存并同步，再补登记回款/)
    assert.equal(guidance.canSync, true)
  }
})

test('recovery states never offer another submission', () => {
  for (const [patch, expected] of [
    [{ linked_sync_id: 'pending-task' }, /关联同步任务/],
    [{ sync_status: 'sync_uncertain' }, /核对原同步结果/],
    [{ receipt_draft: { status: 'armed' } }, /首次回款正在处理中/],
    [{ receipt_draft: { status: 'ready' } }, /首次回款正在处理中/],
    [{ presale_edit_blocked_reason: '先完成原发货批次' }, /先完成原发货批次/],
  ]) {
    const guidance = invoiceReceiptSyncGuidance({ ...saved, ...patch })
    assert.equal(guidance.canSync, false)
    assert.match(guidance.message, expected)
  }
})

test('new, local, closed and synchronized orders do not show a misleading resync prompt', () => {
  for (const patch of [{ id: null }, { transaction_mode: 'local' }, { status: 'cancelled' },
    { status: 'cancel_pending' }, { sync_status: 'synced' }]) {
    assert.equal(invoiceReceiptSyncGuidance({ ...saved, ...patch }), null)
  }
})

test('both editor variants forward the receipt action to the existing save-and-sync flow', () => {
  const read = path => readFileSync(new URL('../src/views/invoice/' + path, import.meta.url), 'utf8')
  for (const file of ['components/InvoiceReceiptFields.vue', 'components/legacy/InvoiceLegacyReceiptFields.vue']) {
    assert.match(read(file), /<InvoiceReceiptActions[^>]*:locked="locked"[^>]*@sync="\$emit\('sync'\)"/)
  }
  assert.match(read('InvoiceManage.vue'), /<InvoiceReceiptFields[^>]*@sync="saveAndSync"/)
  assert.match(read('components/legacy/InvoiceLegacyDrawer.vue'), /<InvoiceLegacyReceiptFields[^>]*@sync="saveAndSync"/)
})
