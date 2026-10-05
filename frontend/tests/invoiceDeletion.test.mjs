import test from 'node:test'
import assert from 'node:assert/strict'
import { buildInvoiceDeletionConfirmation, runRelatedInvoiceDeletion, usesRelatedInvoiceDeletion } from '../src/views/invoice/composables/invoiceDeletionFlow.js'
import { createInvoiceSubmissionGuard } from '../src/views/invoice/composables/invoiceSubmissionGuard.js'

const evidence = {
  version: 'preview-1', invoice_no: 'Rina-KC-1001', outbounds: [{ id: 2, number: 'Rina-KC-1001' }],
  receipts: [{ id: 3, number: 'RC-1', amount: '168.00', currency: 'USD' }], local_receipt_count: 1, blockers: [],
}
function setup(overrides = {}) {
  const calls = []
  return {
    calls,
    deps: {
      preview: async id => { calls.push(['preview', id]); return evidence },
      confirm: async message => { calls.push(['confirm', message]) },
      remove: async (id, body) => { calls.push(['remove', id, body]); return { status: 'remote_deleted' } },
      refresh: async () => { calls.push(['refresh']) },
      notify: (type, message) => { calls.push(['notify', type, message]) },
      showBlockers: async message => { calls.push(['blockers', message]) },
      isCancelled: error => error === 'cancel' || error === 'close',
      ...overrides,
    },
  }
}

test('synced invoices and pending cancellation use admin deletion, unsynced drafts keep local deletion', () => {
  assert.equal(usesRelatedInvoiceDeletion({ status: 'draft', sync_status: 'not_synced' }), false)
  for (const row of [{ xiaoman_order_id: 7 }, { status: 'synced' }, { sync_status: 'synced' }, { status: 'cancel_pending' }]) {
    assert.equal(usesRelatedInvoiceDeletion(row), true)
  }
})

test('confirmation describes related records, receipt currency and amount, archive and no refund', () => {
  const message = buildInvoiceDeletionConfirmation(evidence)
  for (const text of ['Rina-KC-1001', '1 张关联出库单', '1 笔小满回款', '1 笔方舟回款', '原凭证与审计记录', 'RC-1：USD 168.00', '取消归档', '不会退款']) assert.ok(message.includes(text), text)
  const mixed = buildInvoiceDeletionConfirmation({ ...evidence, receipts: [...evidence.receipts, { id: 4, amount: 200, currency: 'EUR' }] })
  assert.ok(mixed.includes('USD 168.00；4：EUR 200.00'))
})

test('one confirmation submits preview version once and refreshes after archival', async () => {
  const { calls, deps } = setup()
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'remote_deleted')
  assert.deepEqual(calls.map(call => call[0]), ['preview', 'confirm', 'remove', 'notify', 'refresh'])
  assert.deepEqual(calls.find(call => call[0] === 'remove'), ['remove', 42, { expected_version: 'preview-1', confirmed: true }])
  assert.equal(calls.find(call => call[0] === 'notify')[1], 'success')
})

test('blockers never prompt approval or submit deletion; completed preview only refreshes', async () => {
  const blocked = setup({ preview: async () => ({ ...evidence, blockers: ['出库已发货', '订单关联信息发生变化'] }) })
  assert.equal(await runRelatedInvoiceDeletion(42, blocked.deps), 'blocked')
  assert.deepEqual(blocked.calls.map(call => call[0]), ['blockers', 'refresh'])
  assert.ok(blocked.calls[0][1].includes('出库已发货\n订单关联信息发生变化'))
  const completed = setup({ preview: async () => ({ ...evidence, complete: true }) })
  assert.equal(await runRelatedInvoiceDeletion(42, completed.deps), 'remote_deleted')
  assert.deepEqual(completed.calls.map(call => call[0]), ['notify', 'refresh'])
})

test('dismissed confirmation never submits deletion', async () => {
  const { calls, deps } = setup({ confirm: async () => { throw 'cancel' } })
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'cancelled')
  assert.deepEqual(calls.map(call => call[0]), ['preview'])
})

test('lost response gives unknown result and refreshes without repeating a POST', async () => {
  let posts = 0
  const { calls, deps } = setup({ remove: async () => { posts++; throw Error('timeout') } })
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'uncertain')
  assert.equal(posts, 1)
  assert.deepEqual(calls.at(-1), ['refresh'])
  const feedback = calls.find(call => call[0] === 'notify')
  assert.equal(feedback[1], 'warning')
  assert.ok(feedback[2].includes('不会重复发送'))
})

test('changed preview or rejected authorization reports blocking reason and refreshes', async () => {
  const { calls, deps } = setup({ remove: async () => { throw { response: { status: 409, data: { detail: '关联单据已变化，请重新确认' } } } } })
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'blocked')
  assert.deepEqual(calls.at(-1), ['refresh'])
  assert.ok(calls.find(call => call[0] === 'notify')[2].includes('关联单据已变化'))
})

test('empty response is treated as unknown and refreshes progress', async () => {
  const { calls, deps } = setup({ remove: async () => null })
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'uncertain')
  assert.deepEqual(calls.at(-1), ['refresh'])
  assert.ok(calls.find(call => call[0] === 'notify')[2].includes('进度待核对'))
})

test('partial deletion refreshes and preserves server evidence in feedback', async () => {
  const { calls, deps } = setup({ remove: async () => ({ status: 'blocked', message: '出库已删除，回款删除被小满拒绝' }) })
  assert.equal(await runRelatedInvoiceDeletion(42, deps), 'blocked')
  assert.deepEqual(calls.at(-1), ['refresh'])
  assert.equal(calls.find(call => call[0] === 'notify')[2], '出库已删除，回款删除被小满拒绝')
})

test('submission guard covers preview and confirmation to reject double clicks', async () => {
  const guard = createInvoiceSubmissionGuard()
  let release, previews = 0
  const { calls, deps } = setup({ preview: async () => { previews++; return new Promise(resolve => { release = () => resolve(evidence) }) } })
  const first = guard.run(42, () => runRelatedInvoiceDeletion(42, deps))
  assert.equal(guard.isPending(42), true)
  assert.deepEqual(await guard.run('42', () => runRelatedInvoiceDeletion(42, deps)), { duplicate: true })
  release()
  await first
  assert.equal(previews, 1)
  assert.equal(calls.filter(call => call[0] === 'remove').length, 1)
  assert.equal(guard.isPending(42), false)
})
