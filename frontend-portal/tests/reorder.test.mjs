import test from 'node:test'
import assert from 'node:assert/strict'
import { createCheckout } from '../src/state/checkout.mjs'
import { createSubmission } from '../src/state/submission.mjs'
import { PortalError } from '../src/api/client.mjs'
const id = '11111111-1111-4111-8111-111111111111', lineKey = '22222222-2222-4222-8222-222222222222'
const product = { item_id: id, model_name: 'Existing cart', color_name: 'Old shade', length_display: '20 in', weight_display: '20 g', sale_unit: 'pack', min_order_qty: 1, step_qty: 1, unit_price: '30.0000', availability: 'available' }
const fresh = () => ({ quote_id: lineKey, content_hash: 'a'.repeat(64), currency: 'USD', status: 'valid', expires_at: '2026-10-01T00:00:00', customer_po: '', remark: 'Previous note', delivery: { contact_name: 'Previous buyer', phone: '123456', address_line1: 'Previous address', country_code: 'GB' }, product_amount: '141.10', total_amount: null, fees: { status: 'pending' }, items: [{ item_id: id, line_key: lineKey, quantity: 4, min_order_qty: 3, step_qty: 2, unit_price: '35.2750', line_amount: '141.10', display_snapshot: { model_name: 'Current client name', color_name: 'New shade', customer_sku: 'NEW-01', length: '22 in', weight: '25 g', unit: 'pack' } }], reorder: { source_request_id: id, changes: [] } })
function setup(overrides = {}) {
  const listeners = new Set(), calls = []
  const api = { session: { me: { account_public_id: id }, capabilities: { place_order: true } }, subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    async reorder(...args) { calls.push(args); return fresh() }, ...overrides }
  const submission = createSubmission({ api })
  const checkout = createCheckout({ api, submission, now: () => Date.parse('2026-09-30T00:00:00+08:00') })
  return { checkout, calls, clear() { api.session = null; listeners.forEach(fn => fn({ reason: 'another-tab' })) } }
}
test('reorder uses only selected history keys, adopts fresh rules/names/address and requires new consent', async () => {
  const { checkout, calls } = setup()
  assert.equal(await checkout.reorder(id, [lineKey]), true)
  assert.deepEqual(calls, [[id, [lineKey], undefined]])
  assert.equal(checkout.state.lines[0].model_name, 'Current client name')
  assert.equal(checkout.state.lines[0].length_display, '22 in')
  assert.equal(checkout.state.lines[0].min_order_qty, 3)
  assert.equal(checkout.state.customer_po, ''); assert.equal(checkout.state.delivery.contact_name, 'Previous buyer')
  assert.equal(checkout.state.acknowledged, false)
  assert.throws(() => checkout.quantity(id, 5), { code: 'INVALID_QUANTITY' })
  checkout.quantity(id, 6); assert.equal(checkout.state.quote, null)
})
test('existing selection needs explicit replacement; declined replacement makes no API call', async () => {
  const { checkout, calls } = setup(); checkout.add(product, 1)
  await assert.rejects(checkout.reorder(id, [lineKey]), { code: 'REPLACEMENT_REQUIRED' })
  assert.equal(calls.length, 0); assert.equal(checkout.state.lines[0].model_name, 'Existing cart')
  await checkout.reorder(id, [lineKey], { replace: true }); assert.equal(checkout.state.lines[0].quantity, 4)
})
test('failed/partial/invalid quote never overwrites existing cart or address', async () => {
  for (const response of [{ ...fresh(), customer_po: 'OLD-PO' }, { ...fresh(), total_amount: '999.00' }, { ...fresh(), items: [] }, { ...fresh(), reorder: { source_request_id: lineKey } }, { ...fresh(), items: [{ ...fresh().items[0], step_qty: undefined }] }]) {
    const { checkout } = setup({ reorder: async () => response }); checkout.add(product, 1); checkout.delivery('contact_name', 'Existing buyer')
    await assert.rejects(checkout.reorder(id, [lineKey], { replace: true }))
    assert.equal(checkout.state.lines[0].model_name, 'Existing cart'); assert.equal(checkout.state.delivery.contact_name, 'Existing buyer')
    assert.equal(checkout.state.quoting, false)
  }
})
test('unavailable lines retain server issue keys for selection recovery', async () => {
  const problem = new PortalError('REORDER_CHANGED', 'Unavailable', { status: 409, issues: [{ line_key: lineKey, error_code: 'PRODUCT_UNAVAILABLE' }] })
  const { checkout } = setup({ reorder: async () => { throw problem } }); checkout.add(product, 1)
  await assert.rejects(checkout.reorder(id, [lineKey], { replace: true }), error => error === problem)
  assert.equal(checkout.state.lines[0].quantity, 1)
})
test('closing dialog drops late quote; concurrent checkout edit wins; logout clears rather than adopts', async () => {
  for (const mode of ['abort', 'edit', 'logout']) {
    let resolve
    const { checkout, clear } = setup({ reorder: () => new Promise(r => { resolve = r }) })
    checkout.add(product, 1)
    const controller = new AbortController()
    const operation = checkout.reorder(id, [lineKey], { replace: true, signal: controller.signal })
    if (mode === 'abort') controller.abort()
    if (mode === 'edit') checkout.quantity(id, 2)
    if (mode === 'logout') clear()
    resolve(fresh()); assert.equal(await operation, false)
    assert.equal(checkout.state.lines.length, mode === 'logout' ? 0 : 1)
    if (mode !== 'logout') assert.equal(checkout.state.lines[0].model_name, 'Existing cart')
    assert.equal(checkout.state.quote, null)
  }
})
test('duplicate/empty selection and concurrent quote requests are rejected', async () => {
  let resolve
  const { checkout } = setup({ reorder: () => new Promise(r => { resolve = r }) })
  await assert.rejects(checkout.reorder(id, []), { code: 'INVALID_SELECTION' })
  await assert.rejects(checkout.reorder(id, [lineKey, lineKey]), { code: 'INVALID_SELECTION' })
  const operation = checkout.reorder(id, [lineKey])
  await assert.rejects(checkout.reorder(id, [lineKey]), { code: 'QUOTE_PENDING' })
  resolve(fresh()); await operation
})
test('abort immediately releases quoting even if transport hangs; late cleanup cannot unlock a newer quote', async () => {
  let finishOld, finishNew, receivedSignal
  const { checkout } = setup({ reorder: (_id, _keys, signal) => { receivedSignal = signal; return new Promise(resolve => { finishOld = resolve }) }, quote: () => new Promise(resolve => { finishNew = resolve }) })
  checkout.add(product, 1)
  for (const [field, value] of Object.entries({ contact_name: 'Test', phone: '123', address_line1: 'Test address', country_code: 'GB' })) checkout.delivery(field, value)
  const abort = new AbortController()
  const old = checkout.reorder(id, [lineKey], { replace: true, signal: abort.signal })
  assert.equal(receivedSignal, abort.signal)
  abort.abort(); assert.equal(checkout.state.quoting, false)
  const newer = checkout.quote(); assert.equal(checkout.state.quoting, true)
  finishOld(fresh()); assert.equal(await old, false)
  assert.equal(checkout.state.quoting, true)
  finishNew(fresh()); await newer; assert.equal(checkout.state.quoting, false)
})
