import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createInvoiceSubmissionGuard } from '../src/views/invoice/composables/invoiceSubmissionGuard.js'
import { feedbackFixture } from './helpers/feedbackFixture.mjs'

const source = readFileSync(new URL('../src/views/invoice/composables/invoiceSyncFlow.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replaceAll('export ', '')
const task = status => ({ id: 'original', invoice_id: 42, active: true, status,
  steps: { order: { status: status === 'done' ? 'done' : status, message: '原任务处理结果' } } })
function setup(api = {}) {
  const calls = [], messages = []
  const mocks = { reactive: value => value, createInvoiceSubmissionGuard,
    getInvoiceLinked: async () => null,
    runInvoiceLinked: async (id, identity) => { calls.push(['linked', id, identity]); return task('done') },
    validateInvoice: async () => { calls.push(['validate']); return { ok: true } },
    syncInvoice: async () => { calls.push(['sync']); return { ok: true } },
    ...feedbackFixture({ ElMessage: Object.fromEntries(['success', 'warning', 'info', 'error'].map(type =>
      [type, message => messages.push({ type, message })])) }), ...api }
  const run = new Function(...Object.keys(mocks), source + '\nreturn validateThenSync')(...Object.values(mocks))
  return { run: options => run(42, () => {}, options), calls, messages }
}

for (const status of ['pending', 'failed']) test(`list sync continues ${status} original task without an ordinary push`, async () => {
  const c = setup({ getInvoiceLinked: async () => task(status) })
  assert.equal(await c.run(), 'success')
  assert.deepEqual(c.calls, [['linked', 42, 'original']])
  assert.equal(c.messages.some(item => item.type === 'error'), false)
})

test('uncertain original result never submits another write', async () => {
  const c = setup({ getInvoiceLinked: async () => task('uncertain') })
  assert.equal(await c.run(), 'failed')
  assert.deepEqual(c.calls, [])
  assert.match(c.messages.at(-1).message, /核对/)
})

test('ordinary sync displays the concrete preflight reason and does not retry', async () => {
  const detail = '订单同步校验未通过：第 2、3 行为同一产品/SKU，缺少可用的独立小满行号'
  let posts = 0
  const c = setup({ syncInvoice: async () => {
    posts++
    throw { response: { status: 409, data: { detail } } }
  } })
  assert.equal(await c.run(), 'failed')
  assert.equal(posts, 1)
  assert.deepEqual(c.messages, [{ type: 'warning', message: detail }])
})

test('lost continuation response reads completed original result without another POST or failure toast', async () => {
  let reads = 0, posts = 0
  const c = setup({ getInvoiceLinked: async () => task(++reads === 1 ? 'pending' : 'done'),
    runInvoiceLinked: async () => { posts++; throw Error('lost response') } })
  assert.equal(await c.run(), 'success')
  assert.equal(posts, 1)
  assert.equal(c.messages.some(item => ['error', 'warning'].includes(item.type)), false)
})

test('a completed historical task does not suppress an ordinary sync', async () => {
  const c = setup({ getInvoiceLinked: async () => ({ ...task('done'), active: false }) })
  assert.equal(await c.run(), 'success')
  assert.deepEqual(c.calls, [['validate'], ['sync']])
})

test('a newly created linked task between read and ordinary push resumes once', async () => {
  let reads = 0
  const c = setup({ getInvoiceLinked: async () => ++reads === 1 ? null : task('pending'),
    syncInvoice: async () => { throw { response: { status: 409, headers: { 'x-ark-linked-sync': 'pending', 'x-ark-linked-sync-id': 'original' } } } } })
  assert.equal(await c.run(), 'success')
  assert.deepEqual(c.calls, [['validate'], ['linked', 42, 'original']])
})

test('conflicting original task completed before readback is reported as success', async () => {
  let reads = 0
  const c = setup({ getInvoiceLinked: async () => ++reads === 1 ? null : { ...task('done'), active: false },
    syncInvoice: async () => { throw { response: { status: 409, headers: { 'x-ark-linked-sync': 'pending', 'x-ark-linked-sync-id': 'original' } } } } })
  assert.equal(await c.run(), 'success')
  assert.deepEqual(c.calls, [['validate']])
  assert.equal(c.messages.some(item => ['warning', 'error'].includes(item.type)), false)
})

test('account or view changes during lookup stop all writes and feedback', async () => {
  let current = true
  const c = setup({ getInvoiceLinked: async () => { current = false; return task('pending') } })
  await c.run({ isCurrent: () => current })
  assert.deepEqual(c.calls, [])
  assert.deepEqual(c.messages, [])
})

test('lost response cannot borrow success from a different task', async () => {
  let reads = 0
  const c = setup({ getInvoiceLinked: async () => ++reads === 1 ? task('pending') : { ...task('done'), id: 'other' },
    runInvoiceLinked: async () => { throw Error('lost response') } })
  assert.notEqual(await c.run(), 'success')
  assert.equal(c.messages.some(item => item.type === 'success'), false)
})

test('running task is only observed until background completion', async () => {
  let reads = 0, waits = 0
  const c = setup({ getInvoiceLinked: async () => task(++reads < 3 ? 'running' : 'done') })
  assert.equal(await c.run({ wait: async () => { waits++ } }), 'success')
  assert.equal(waits, 2)
  assert.deepEqual(c.calls, [])
  assert.match(c.messages[0].message, /修改已保存.*继续同步/)
})

test('observation has a bound while background processing remains pending', async () => {
  let waits = 0, posts = 0
  const c = setup({ getInvoiceLinked: async () => task('pending'),
    runInvoiceLinked: async () => { posts++; return task('pending') } })
  assert.equal(await c.run({ wait: async () => { waits++ } }), 'pending')
  assert.equal(waits, 20); assert.equal(posts, 1)
  assert.equal(c.messages.some(item => ['warning', 'error'].includes(item.type)), false)
})
