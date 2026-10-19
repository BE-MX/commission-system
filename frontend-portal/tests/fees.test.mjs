import test from 'node:test'
import assert from 'node:assert/strict'
import { feeSummary, formatWeight, surchargeLabel } from '../src/state/fees.mjs'
import { createCheckout } from '../src/state/checkout.mjs'
import { createSubmission } from '../src/state/submission.mjs'

const confirmed = { status: 'confirmed', weight_grams: '60', shipping_amount: '40.00', surcharge_amount: '6.05',
  surcharge_name: 'Payment surcharge (PayPal 5%)', total_amount: '127.05', manual_above_grams: 2000 }

test('confirmed estimate shows weight, shipping, surcharge and total', () => {
  const summary = feeSummary({ fee_estimate: confirmed })
  assert.equal(summary.confirmed, true)
  assert.deepEqual(summary.rows.map(([label]) => label), ['Total weight', 'Shipping', 'Payment surcharge (PayPal 5%)', 'Total'])
  assert.equal(summary.rows[0][1], '60 g')
  const bank = feeSummary({ fee_estimate: { ...confirmed, surcharge_amount: '0.00', surcharge_name: '', total_amount: '121.00' } })
  assert.deepEqual(bank.rows.map(([label]) => label), ['Total weight', 'Shipping', 'Total'])
})

test('manual and legacy quotes never show an invented total', () => {
  const heavy = feeSummary({ fee_estimate: { status: 'manual', reason: 'over_limit', weight_grams: '2020', manual_above_grams: 2000 } })
  assert.equal(heavy.confirmed, false)
  assert.match(heavy.note, /over 2 kg/)
  assert.deepEqual(heavy.rows.at(-1), ['Final total', 'To be confirmed'])
  const legacy = feeSummary({ fee_estimate: null })
  assert.equal(legacy.confirmed, false)
  assert.deepEqual(legacy.rows[0], ['Shipping & other charges', 'Pending review'])
})

test('weights and surcharge labels are readable', () => {
  assert.equal(formatWeight('250'), '250 g')
  assert.equal(formatWeight('1250'), '1.25 kg')
  assert.equal(formatWeight(null), '—')
  assert.equal(surchargeLabel({ surcharge_percent: '5.00' }), '+5% payment surcharge')
  assert.equal(surchargeLabel({ surcharge_percent: '0.00' }), 'No surcharge')
})

test('payment method is sent with the quote and changing it discards the review', async () => {
  const calls = []
  const api = { session: { me: { account_public_id: 'a' }, capabilities: { place_order: true } }, subscribe: () => () => {},
    async quote(body) { calls.push(body); return { ...body, quote_id: 'q', content_hash: 'a'.repeat(64), currency: 'USD', status: 'valid', expires_at: '2026-09-30T12:10:00', items: [{}] } } }
  const submission = createSubmission({ api, storage: null, newKey: () => 'k' })
  const checkout = createCheckout({ api, submission, now: () => Date.parse('2026-09-30T04:00:00Z') })
  checkout.add({ item_id: 'i', unit_price: '1.0000', availability: 'available', min_order_qty: 1, step_qty: 1 }, 1)
  for (const [field, value] of Object.entries({ contact_name: 'B', phone: '123456', address_line1: 'A', country_code: 'GB' })) checkout.delivery(field, value)
  await checkout.quote()
  assert.equal('payment_term_code' in calls[0], false)
  checkout.paymentTerm('paypal')
  assert.equal(checkout.state.quote, null)
  await checkout.quote()
  assert.equal(calls[1].payment_term_code, 'paypal')
  assert.throws(() => checkout.paymentTerm('Bad Code'))
})
