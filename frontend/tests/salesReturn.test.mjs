import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { webcrypto } from 'node:crypto'
import * as vue from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as state from '../src/views/sales-return/returnState.js'

const fixture = () => ({ order_id: 'order-1', return_type: 'return_refund', reason_code: 'quality', reason: '商品质量核验后退款', refund_amount: '99.99', lines: [{ source_key: 'out:1:line:2', selected: true, quantity: '2', reduction_amount: '100.01' }] })
test('decimal money survives payload without floating point sums; unselected source lines stay excluded', () => {
  const form = fixture()
  form.lines.push({ source_key: 'other-line', selected: false, quantity: '100', reduction_amount: '10.00' })
  const body = state.draftPayload(form)
  assert.equal(body.lines[0].reduction_amount, '100.01')
  assert.equal(body.refund_amount, '99.99')
  assert.equal(body.lines[0].quantity, 2)
  assert.equal(body.lines.length, 1)
  assert.equal(state.validateDraft(body), '')
})
test('blank refund delegates default to server while explicit zero is preserved', () => {
  assert.equal(state.draftPayload({ ...fixture(), refund_amount: '' }).refund_amount, null)
  assert.equal(state.draftPayload({ ...fixture(), refund_amount: '0' }).refund_amount, '0')
})
test('response-loss comparison preserves decimal meaning across server normalization and line ordering', () => {
  const first = state.draftPayload(fixture())
  first.refund_amount = '0.00'
  const second = JSON.parse(JSON.stringify(first)); second.refund_amount = '0'; second.lines[0].reduction_amount = '100.0100'
  assert.equal(state.draftComparison(first), state.draftComparison(second))
})
test('financial validation rejects exponent, signs, excess cents and non-integer quantities', () => {
  for (const value of ['1e3', '-1', '+1', '1.001', 'Infinity', '']) {
    const body = state.draftPayload(fixture()); body.lines[0].reduction_amount = value
    assert.notEqual(state.validateDraft(body), '', value)
  }
  for (const value of [0, -1, 1.5, NaN, 1000001]) {
    const body = state.draftPayload(fixture()); body.lines[0].quantity = value
    assert.notEqual(state.validateDraft(body), '')
  }
})

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function harness(filename, initialProps = {}) {
  const code = fs.readFileSync(new URL(`../src/views/sales-return/${filename}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(code)
  const compiled = compileScript(descriptor, { id: 'return-test' }).content
  const calls = [], queue = new Map(), events = []
  const defaults = { getReturnCustomers: { items: [] }, getReturnOrders: { items: [] }, getReturnOrderLines: { order: { id: 'order-1', currency: 'USD' }, lines: [] }, previewSalesReturn: { quote_version: 'a'.repeat(64), reduction_amount: '100.01', refund_amount: '99.99' }, createSalesReturn: { id: 5 }, getSalesReturn: { id: 5, status: 'draft', version: 1 } }
  const api = Object.fromEntries(['getReturnCustomers', 'getReturnOrders', 'getReturnOrderLines', 'previewSalesReturn', 'createSalesReturn', 'updateSalesReturn', 'getSalesReturn', 'activateSalesReturn', 'reverseSalesReturn', 'recordReturnCash', 'receiveSalesReturn', 'inspectSalesReturn', 'stockSalesReturn', 'deleteSalesReturn'].map(name => [name, (...args) => {
    calls.push({ name, args: JSON.parse(JSON.stringify(args)) })
    return queue.get(name)?.length ? queue.get(name).shift().promise : Promise.resolve(defaults[name] || {})
  }]))
  const context = vm.createContext({ console, crypto: webcrypto, JSON, Number, String, Object, Promise })
  const imports = {
    vue,
    '@/api/salesReturn': api,
    './returnState': { ...state, requestKey: () => webcrypto.randomUUID() },
    '@/utils/errors': { errorMessage: error => error.message || '接口校验失败' },
    '@/utils/datetime': { formatBeijingDateTime: value => value },
    '@/utils/feedback': { msgSuccessText() {}, msgWarning() {}, confirmAction: (...args) => { calls.push({ name: 'confirmAction', args }); return Promise.resolve() }, promptAction: () => Promise.resolve({ value: '完整而可核验的真实资金凭据' }), isFeedbackCancelled: () => false },
  }
  const module = new vm.SourceTextModule(compiled, { context })
  await module.link(name => {
    const exports = imports[name] || (name.endsWith('.vue') ? { default: {} } : null)
    assert.ok(exports, name)
    return new vm.SyntheticModule(Object.keys(exports), function () { for (const [key, value] of Object.entries(exports)) this.setExport(key, value) }, { context })
  })
  await module.evaluate()
  const props = vue.reactive({ modelValue: false, record: null, prefill: {}, returnId: 5, ...initialProps })
  const scope = vue.effectScope()
  const page = scope.run(() => module.namespace.default.setup(props, { expose() {}, emit: (...args) => events.push(args) }))
  return { page, props, calls, events, stop: () => scope.stop(), wait(name) { const result = deferred(); const items = queue.get(name) || []; items.push(result); queue.set(name, items); return result } }
}
async function run(filename, fn) { const h = await harness(filename); try { await fn(h) } finally { h.stop() } }

test('editing any money field invalidates an earlier preview; save cannot use stale quote', () => run('ReturnDraftDrawer', async h => {
  Object.assign(h.page.form, fixture())
  await h.page.preview()
  assert.equal(h.page.quoteCurrent.value, true)
  h.page.form.refund_amount = '99.98'
  assert.equal(h.page.quoteCurrent.value, false)
  await h.page.save()
  assert.equal(h.calls.some(call => call.name === 'createSalesReturn'), false)
}))

test('closing the drawer after a successful save does not ask to discard already saved changes', () => run('ReturnDraftDrawer', async h => {
  Object.assign(h.page.form, fixture()); await h.page.preview()
  await h.page.save()
  assert.ok(h.events.some(([event]) => event === 'saved'))
  await h.page.close(false)
  assert.equal(h.calls.filter(call => call.name === 'confirmAction').length, 0)
}))

test('reconciled update response loss marks the verified draft saved before closing', async () => {
  const h = await harness('ReturnDraftDrawer', { record: { id: 5, version: 1 } })
  try {
    Object.assign(h.page.form, fixture()); await h.page.preview()
    const update = h.wait('updateSalesReturn'), read = h.wait('getSalesReturn')
    const task = h.page.save()
    update.reject({ response: { status: 409 }, message: 'stale version after response loss' })
    const saved = state.draftPayload(fixture())
    read.resolve({ ...saved, id: 5, version: 2, status: 'draft', items: saved.lines })
    await task
    assert.ok(h.events.some(([event]) => event === 'saved'))
    await h.page.close(false)
    assert.equal(h.calls.filter(call => call.name === 'confirmAction').length, 0)
  } finally { h.stop() }
})

test('failed saves still ask to discard changes and uncertain saves remain locked', () => run('ReturnDraftDrawer', async h => {
  Object.assign(h.page.form, fixture()); await h.page.preview()
  const rejected = h.wait('createSalesReturn'), task = h.page.save()
  rejected.reject({ response: { status: 422 }, message: 'invalid draft' }); await task
  await h.page.close(false)
  assert.equal(h.calls.filter(call => call.name === 'confirmAction').length, 1)
  const uncertain = h.wait('createSalesReturn'), retry = h.page.save()
  uncertain.reject(new Error('response lost')); await retry
  const closes = h.events.filter(([event]) => event === 'update:modelValue').length
  await h.page.close(false)
  assert.equal(h.events.filter(([event]) => event === 'update:modelValue').length, closes)
  assert.ok(h.page.pending.value)
}))
test('uncertain draft creation retains exact request body/key and prevents duplicate parallel writes', () => run('ReturnDraftDrawer', async h => {
  Object.assign(h.page.form, fixture()); await h.page.preview()
  const failure = h.wait('createSalesReturn'), first = h.page.save()
  await h.page.save()
  assert.equal(h.calls.filter(call => call.name === 'createSalesReturn').length, 1)
  failure.reject(new Error('response lost')); await first
  assert.ok(h.page.pending.value)
  const original = h.calls.find(call => call.name === 'createSalesReturn').args[0]
  h.page.form.reason = 'unsaved mutation cannot change a pending request'
  await h.page.save()
  const writes = h.calls.filter(call => call.name === 'createSalesReturn')
  assert.deepEqual(writes[1].args[0], original)
  assert.equal(h.page.pending.value, null)
}))
test('older order line response cannot overwrite a newer selection', () => run('ReturnDraftDrawer', async h => {
  const first = h.wait('getReturnOrderLines'), second = h.wait('getReturnOrderLines')
  const a = h.page.loadLines('old'), b = h.page.loadLines('new')
  second.resolve({ order: { id: 'new' }, lines: [{ source_key: 'new-line' }] }); await b
  first.resolve({ order: { id: 'old' }, lines: [{ source_key: 'old-line' }] }); await a
  assert.equal(h.page.form.lines[0].source_key, 'new-line')
}))
test('forced close suppresses a late draft-save response and prevents reopening private details', () => run('ReturnDraftDrawer', async h => {
  h.props.modelValue = true; await vue.nextTick(); await new Promise(resolve => setImmediate(resolve))
  Object.assign(h.page.form, fixture()); await h.page.preview()
  const write = h.wait('createSalesReturn'), task = h.page.save()
  h.props.modelValue = false; await vue.nextTick()
  write.resolve({ id: 9 }); await task
  assert.equal(h.events.some(([event]) => event === 'saved'), false)
}))
test('preselected query can initialize the drawer on its first mount', async () => {
  const h = await harness('ReturnDraftDrawer', { modelValue: true, prefill: { order_id: 'order-from-query' } })
  try {
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(h.page.form.order_id, 'order-from-query')
    assert.equal(h.calls.find(call => call.name === 'getReturnOrderLines').args[0], 'order-from-query')
  } finally { h.stop() }
})
test('activate retry retains exact quote version and request key after response loss', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'draft', version: 1 }
  const failure = h.wait('activateSalesReturn'), task = h.page.act('activate', { version: 1, quote_version: 'a'.repeat(64) })
  failure.reject(new Error('response lost')); await task
  assert.ok(h.page.pending.value)
  await h.page.executePending()
  const writes = h.calls.filter(call => call.name === 'activateSalesReturn')
  assert.deepEqual(writes[0].args, writes[1].args)
}))
test('cash/stock payloads follow strict schemas without unrelated request/event fields', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'effective', version: 1 }
  await h.page.act('cash', { version: 1, status: 'paid', evidence: 'real payment evidence' })
  assert.equal('request_key' in h.calls.find(call => call.name === 'recordReturnCash').args[1], false)
  await h.page.act('stock', { event_id: 9, reference: 'authority-reference' })
  const stock = h.calls.find(call => call.name === 'stockSalesReturn')
  assert.equal(stock.args[1], 9)
  assert.equal('event_id' in stock.args[2], false)
  assert.ok(stock.args[2].request_key)
}))
test('receiving requires integer quantities and an exact inspection sum before requesting', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'effective', version: 1 }
  Object.assign(h.page.receiving, { item_id: 3, quantity: '3', accepted_quantity: '1', rejected_quantity: '0', pending_quantity: '1' })
  await h.page.receive()
  assert.equal(h.calls.some(call => call.name === 'receiveSalesReturn'), false)
  h.page.receiving.pending_quantity = '2'; await h.page.receive()
  const received = h.calls.find(call => call.name === 'receiveSalesReturn').args[1]
  assert.equal(received.quantity, 3)
  assert.equal(received.pending_quantity, 2)
}))
test('continued inspection only classifies original pending goods and permits partial progress', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'effective', version: 9 }
  h.page.openInspection({ id: 11, version: 3, quantity: 10, accepted_quantity: 2, rejected_quantity: 1, pending_quantity: 7 })
  Object.assign(h.page.inspection, { accepted: '3', rejected: '1', note: '本次抽检已核验' })
  assert.equal(h.page.inspectionRemaining.value, 3)
  await h.page.inspect()
  const call = h.calls.find(call => call.name === 'inspectSalesReturn')
  assert.deepEqual(call.args, [5, 11, { version: 3, accepted_quantity: 5, rejected_quantity: 2, pending_quantity: 3, note: '本次抽检已核验' }])
  assert.equal('quantity' in call.args[2], false)
  assert.equal('request_key' in call.args[2], false)
  assert.equal(h.page.inspectionVisible.value, false)
}))
test('continued inspection blocks negative, fractional, excessive, unchanged and undocumented updates', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'effective' }
  h.page.openInspection({ id: 11, version: 1, quantity: 4, accepted_quantity: 1, rejected_quantity: 0, pending_quantity: 3 })
  for (const [accepted, rejected, note] of [['-1', '0', '检验完成'], ['1.5', '0', '检验完成'], ['3', '1', '检验完成'], ['0', '0', '检验完成'], ['1', '0', '']]) {
    Object.assign(h.page.inspection, { accepted, rejected, note }); await h.page.inspect()
    assert.ok(h.page.inspectionError.value)
  }
  assert.equal(h.calls.some(call => call.name === 'inspectSalesReturn'), false)
}))
test('uncertain continued inspection retries original version and cumulative classifications unchanged', () => run('ReturnDetailDrawer', async h => {
  h.page.detail.value = { id: 5, status: 'effective' }
  h.page.openInspection({ id: 11, version: 1, quantity: 4, accepted_quantity: 1, rejected_quantity: 0, pending_quantity: 3 })
  Object.assign(h.page.inspection, { accepted: '3', rejected: '0', note: '全部待检完成' })
  const failure = h.wait('inspectSalesReturn'), task = h.page.inspect()
  failure.reject(new Error('response lost')); await task
  assert.ok(h.page.pending.value)
  h.page.inspection.accepted = '0'
  await h.page.executePending()
  const calls = h.calls.filter(call => call.name === 'inspectSalesReturn')
  assert.deepEqual(calls[0].args, calls[1].args)
  assert.equal(calls[1].args[2].pending_quantity, 0)
}))
test('warehouse UI explicitly reports pending integration and offers no known-failing stock command', () => {
  const source = fs.readFileSync(new URL('../src/views/sales-return/ReturnDetailDrawer.vue', import.meta.url), 'utf8')
  assert.match(source, /待权威入库接入/)
  assert.doesNotMatch(source, /@click="stock\(row\)"/)
})
