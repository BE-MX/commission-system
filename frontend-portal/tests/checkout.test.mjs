import test from 'node:test'
import assert from 'node:assert/strict'
import { createCheckout, minimumQuantity, quantityFor, quoteDeadline } from '../src/state/checkout.mjs'
import { createSubmission } from '../src/state/submission.mjs'
import { PortalError } from '../src/api/client.mjs'
import { money, beijingTime } from '../src/presentation.mjs'

const item = { item_id: '11111111-1111-4111-8111-111111111111', model_name: 'Test weft', color_name: 'Test blonde', customer_sku: 'CUSTOM-01', unit_price: '35.2750', sale_unit: 'pack', min_order_qty: 3, step_qty: 2, availability: 'available' }
const key = '33333333-3333-4333-8333-333333333333'
const receipt = { request_id: key, request_no: 'TEST-001' }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function setup(overrides = {}) {
  const listeners = new Set(), calls = [], values = new Map()
  const api = { session: { me: { account_public_id: key }, capabilities: { place_order: true } },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    async quote(body) { calls.push(body); return { ...structuredClone(body), quote_id: key, content_hash: 'a'.repeat(64), currency: 'USD', status: 'valid', expires_at: '2026-09-30T12:10:00', product_amount: '141.10' } },
    async submit(id, body) { calls.push({ id, body }); return receipt },
    async orderByKey() { return receipt }, ...overrides }
  const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) }
  const submission = createSubmission({ api, storage, newKey: () => key })
  const checkout = createCheckout({ api, submission, now: () => Date.parse('2026-09-30T04:00:00Z') })
  const fill = () => {
    checkout.add(item, 4)
    for (const [field, value] of Object.entries({ contact_name: 'Test buyer', phone: '123456', address_line1: 'Test address', country_code: 'gb' })) checkout.delivery(field, value)
  }
  const clear = () => { api.session = null; for (const listener of listeners) listener({ reason: 'another-tab', session: null }) }
  return { api, checkout, submission, calls, storage, values, fill, clear }
}
test('minimum is a multiple of step, not an offset from minimum; no fractional/coerced quantity', () => {
  assert.equal(minimumQuantity(item), 4)
  assert.equal(quantityFor(item, '6'), 6)
  for (const value of [3, 5, 4.5, -4, 0, true, '4e0', '04', '10002']) assert.throws(() => quantityFor(item, value))
  assert.equal(minimumQuantity({ min_order_qty: 9999, step_qty: 10001 }), null)
})
test('cart merges same SKU, validates sum and copies server display; absent price and stock block add', () => {
  const { checkout } = setup(), product = { ...item }
  checkout.add(product, 4); checkout.add(product, 6); product.model_name = 'Changed outside'
  assert.equal(checkout.state.lines.length, 1); assert.equal(checkout.state.lines[0].quantity, 10)
  assert.equal(checkout.state.lines[0].model_name, 'Test weft')
  assert.throws(() => checkout.add(item, 10000))
  assert.throws(() => checkout.add({ ...item, unit_price: null }, 4))
  assert.throws(() => checkout.add({ ...item, availability: 'unknown' }, 4))
})
test('quote sends stable IDs/quantities only; server owns price; editing any detail discards quote and consent', async () => {
  const { checkout, fill, calls } = setup(); fill(); await checkout.quote()
  assert.deepEqual(calls[0].items, [{ item_id: item.item_id, quantity: 4 }])
  assert.equal(calls[0].delivery.country_code, 'GB')
  checkout.acknowledge(true); checkout.details('remark', 'Changed')
  assert.equal(checkout.state.quote, null); assert.equal(checkout.state.acknowledged, false)
  await checkout.quote(); checkout.acknowledge(true); checkout.quantity(item.item_id, 6)
  assert.equal(checkout.state.quote, null); assert.equal(checkout.state.acknowledged, false)
})
test('late quote after edit cannot overwrite current selection', async () => {
  const waiting = deferred(), { checkout, fill } = setup({ quote: () => waiting.promise }); fill()
  const request = checkout.quote(); checkout.delivery('city', 'Updated')
  waiting.resolve({ quote_id: key }); await request
  assert.equal(checkout.state.quote, null); assert.equal(checkout.state.quoting, false)
})
test('logout clears cart/address/PO/quote and drops late results', async () => {
  const waiting = deferred(), { checkout, fill, clear } = setup({ quote: () => waiting.promise }); fill(); checkout.details('customer_po', 'PRIVATE')
  const request = checkout.quote(); clear(); waiting.resolve({ quote_id: key }); await request
  assert.equal(checkout.state.lines.length, 0); assert.equal(checkout.state.delivery.contact_name, '')
  assert.equal(checkout.state.customer_po, ''); assert.equal(checkout.state.quote, null)
})
test('no submit without explicit confirmation; one frozen body; pending cart cannot mutate; success clears PII', async () => {
  const waiting = deferred(), { checkout, fill, values } = setup({ submit: () => waiting.promise }); fill(); await checkout.quote()
  assert.throws(() => checkout.submit(), { code: 'CONFIRMATION_REQUIRED' })
  checkout.acknowledge(true); const request = checkout.submit()
  assert.throws(() => checkout.submit(), { code: 'SUBMISSION_PENDING' })
  assert.throws(() => checkout.quantity(item.item_id, 6), { code: 'SUBMISSION_PENDING' })
  assert.throws(() => checkout.delivery('city', 'changed'), { code: 'SUBMISSION_PENDING' })
  assert.equal([...values.values()][0], JSON.stringify({ key }))
  waiting.resolve(receipt); await request
  assert.equal(checkout.state.receipt.request_no, 'TEST-001'); assert.equal(checkout.state.lines.length, 0)
  assert.equal(checkout.state.delivery.address_line1, ''); assert.equal(values.size, 0)
})
test('unknown submission and 404 recovery cannot create a new checkout key', async () => {
  const { checkout, submission, fill } = setup({ submit: async () => { throw new PortalError('NETWORK', 'Unknown', { uncertain: true }) }, orderByKey: async () => { throw new PortalError('NOT_FOUND', 'Not found', { status: 404 }) } })
  fill(); await checkout.quote(); checkout.acknowledge(true); await checkout.submit()
  assert.equal(checkout.state.submission.status, 'uncertain')
  assert.throws(() => checkout.add(item, 4), { code: 'SUBMISSION_PENDING' })
  assert.throws(() => checkout.submit(), { code: 'SUBMISSION_PENDING' })
  await submission.recover(); assert.equal(checkout.state.submission.status, 'uncertain')
})
test('known submit rejection preserves draft but invalidates review; session capability blocks ordering', async () => {
  const { checkout, api, fill } = setup({ submit: async () => { throw new PortalError('PRICE_CHANGED', 'Refresh your quote.', { status: 409 }) } })
  fill(); await checkout.quote(); checkout.acknowledge(true); await checkout.submit()
  assert.equal(checkout.state.quote, null); assert.equal(checkout.state.lines.length, 1)
  assert.equal(checkout.state.error.code, 'PRICE_CHANGED')
  api.session.capabilities.place_order = false
  assert.throws(() => checkout.add(item, 4), { code: 'ORDERING_UNAVAILABLE' })
})
test('expired or malformed server quote never enables submit', async () => {
  for (const expires_at of ['2026-09-30T12:00:00', 'garbage']) {
    const { checkout, fill } = setup({ quote: async body => ({ ...body, quote_id: key, content_hash: 'a'.repeat(64), currency: 'USD', status: 'valid', expires_at }) })
    fill(); await checkout.quote(); assert.equal(checkout.state.quote, null)
    assert.equal(checkout.state.error.code, 'QUOTE_UNAVAILABLE')
  }
})
test('Beijing timestamps retain intended instant; currency formatting preserves exact decimal strings', () => {
  assert.equal(quoteDeadline('2026-09-30T00:01:00'), Date.parse('2026-09-29T16:01:00Z'))
  assert.equal(quoteDeadline('2026-09-29T16:01:00Z'), quoteDeadline('2026-09-30T00:01:00'))
  assert.match(beijingTime('2026-09-29T16:01:00Z'), /30 Sept 2026, 00:01 \(Beijing\)/)
  assert.equal(money('999999999999999999.99'), 'USD 999,999,999,999,999,999.99')
  assert.equal(money(null), 'To be confirmed'); assert.equal(money('3.275'), 'To be confirmed')
})


test('unavailable rows preserve draft and recover after removal; foreign issue IDs are ignored', async () => {
  let unavailable = true
  const removed = '22222222-2222-4222-8222-222222222222'
  const { checkout, fill } = setup({ quote: async body => {
    if (unavailable) throw new PortalError('RESOURCE_NOT_FOUND', 'Remove unavailable products', { status: 404, issues: [
      { item_id: removed, code: 'ITEM_UNAVAILABLE' }, { item_id: 'foreign', code: 'ITEM_UNAVAILABLE' },
      { item_id: item.item_id, code: 'ARBITRARY' }, null] })
    return { ...body, quote_id: key, content_hash: 'a'.repeat(64), currency: 'USD', status: 'valid', expires_at: '2026-09-30T12:10:00', product_amount: '141.10' }
  } })
  fill(); checkout.add({ ...item, item_id: removed, model_name: 'Withdrawn weft' }, 4)
  checkout.details('customer_po', 'Keep PO')
  const delivery = structuredClone(checkout.state.delivery)
  await checkout.quote()
  assert.equal(checkout.state.lines.length, 2)
  assert.equal(checkout.state.lines.find(row => row.item_id === removed).unavailable, true)
  assert.equal(checkout.state.lines.find(row => row.item_id === item.item_id).unavailable, undefined)
  assert.throws(() => checkout.quantity(removed, 6), { code: 'ITEM_UNAVAILABLE' })
  assert.deepEqual(checkout.state.delivery, delivery)
  checkout.remove(removed); unavailable = false; await checkout.quote()
  assert.equal(checkout.state.lines.length, 1)
  assert.equal(checkout.state.quote.items[0].item_id, item.item_id)
  assert.equal(checkout.state.customer_po, 'Keep PO')
  assert.deepEqual(checkout.state.delivery, delivery)
})

test('late unavailable error after draft edit cannot mark a newer selection', async () => {
  let reject
  const waiting = new Promise((_, fail) => { reject = fail })
  const { checkout, fill } = setup({ quote: () => waiting }); fill()
  const pending = checkout.quote(); checkout.delivery('city', 'New city')
  reject(new PortalError('RESOURCE_NOT_FOUND', 'Old response', { issues: [{ item_id: item.item_id, code: 'ITEM_UNAVAILABLE' }] }))
  await pending
  assert.equal(checkout.state.lines[0].unavailable, undefined)
  assert.equal(checkout.state.error, null)
})
