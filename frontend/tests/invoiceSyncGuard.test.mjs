import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createInvoiceSubmissionGuard } from '../src/views/invoice/composables/invoiceSubmissionGuard.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const syncFlow = read('../src/views/invoice/composables/invoiceSyncFlow.js')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')
const invoiceView = read('../src/views/invoice/InvoiceManage.vue')
const totalsFooter = read('../src/views/invoice/components/InvoiceTotalsFooter.vue')

function deferred() {
  let resolve
  const promise = new Promise(resolvePromise => { resolve = resolvePromise })
  return { promise, resolve }
}

test('shared invoice sync guard only accepts one in-flight request per invoice', async () => {
  const guard = createInvoiceSubmissionGuard()
  const gate = deferred()
  let submitCalls = 0
  const first = guard.run(42, async () => {
    submitCalls += 1
    return gate.promise
  })

  assert.equal(guard.isPending('42'), true)
  assert.deepEqual(await guard.run('42', async () => { submitCalls += 1 }), { duplicate: true })
  assert.equal(submitCalls, 1)

  gate.resolve('synced')
  assert.deepEqual(await first, { duplicate: false, value: 'synced' })
  assert.equal(guard.isPending(42), false)
})

test('sync guard isolates invoice IDs and releases failed submissions for retry', async () => {
  const guard = createInvoiceSubmissionGuard()
  const gate = deferred()
  const first = guard.run(1, () => gate.promise)
  assert.deepEqual(await guard.run(2, async () => 'second'), { duplicate: false, value: 'second' })

  gate.resolve('first')
  await first
  await assert.rejects(guard.run(1, async () => { throw new Error('failed') }), /failed/)
  assert.equal(guard.isPending(1), false)
  assert.deepEqual(await guard.run(1, async () => 'retry'), { duplicate: false, value: 'retry' })
})

test('both invoice sync entry points expose loading state and guard save-before-sync', () => {
  assert.match(invoiceView, /:loading="isInvoiceSyncing\(row\.id\)"/)
  assert.match(invoiceView, /:syncing="saveAndSyncSubmitting"/)
  assert.match(totalsFooter, /:loading="syncing"/)
  assert.match(editor, /if \(saveAndSyncSubmitting\.value\) \{[\s\S]*正在保存并同步，请勿重复提交/)
  assert.match(editor, /saveAndSyncSubmitting\.value = true[\s\S]*finally \{\s*saveAndSyncSubmitting\.value = false/)
  assert.match(syncFlow, /正在同步，请勿重复提交/)
  assert.match(syncFlow, /INVOICE_SYNC_OUTCOME\.DUPLICATE/)
})
