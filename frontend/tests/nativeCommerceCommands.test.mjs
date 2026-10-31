import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { newRequestKey } from '../src/utils/requestKey.js'
import { isAmount } from '../src/utils/validators.js'

function load(relative, modules) {
  let source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const names = [...source.matchAll(/export function (\w+)/g)].map(match => match[1])
  source = source.replace(/import\s+(\{[^}]+\})\s+from\s+['"]([^'"]+)['"]/g, (_, binding, key) => `const ${binding} = modules[${JSON.stringify(key)}]`)
    .replaceAll('export function ', 'function ')
  return new Function('modules', `${source}\nreturn { ${names.join(', ')} }`)(modules)
}
const money = load('../src/views/finance/native/decimal.js', { '@/utils/validators': { isAmount } })
const { useNativeCommand } = load('../src/views/finance/native/useNativeCommand.js', { vue: Vue, '@/utils/requestKey': { newRequestKey }, '@/utils/errors': { errorMessage: error => error.message }, '@/utils/feedback': { isFeedbackCancelled: error => error === 'cancel' } })
const { makeOrderDraft, draftPayload } = load('../src/views/invoice/native/draft.js', { '@/utils/datetime': { currentBeijingDate: () => '2026-10-03' }, '@/views/finance/native/decimal': money })
const { allocationPayload } = load('../src/views/finance/native/allocation.js', { './decimal': money })

test('native amounts retain cents at the schema boundary and reject exponent/overflow input', () => {
  assert.equal(money.formatNativeMoney('999999999999.99'), '999,999,999,999.99')
  assert.equal(money.fromUnits(money.toUnits('-0.01')), '-0.01')
  assert.throws(() => money.requireAmount('1000000000000.00', 'amount'))
  assert.throws(() => money.requireAmount('1e5', 'amount'))
  assert.equal(money.lineAmount({ quantity: 3, price_per_piece: '0.3333', discount_amount: '-0.01' }), 99n)
})

test('command retries reuse identity after uncertain failure; edit and restore creates a new attempt', async () => {
  let key = 0
  const command = useNativeCommand(() => `key-${++key}`), calls = []
  let amount = '8.00'
  const attempt = { payload: () => ({ amount }), send: async body => { calls.push(body); throw new Error('response lost') } }
  await command.run(attempt); await command.run(attempt)
  assert.equal(calls[0].request_key, calls[1].request_key)
  amount = '9.00'; command.reset(); amount = '8.00'; command.reset()
  await command.run(attempt)
  assert.notEqual(calls[1].request_key, calls[2].request_key)
  assert.equal(command.failure.value, 'response lost')
})

test('command locks before async validation and keeps cancellation out of failures', async () => {
  const command = useNativeCommand(() => 'key'), calls = []
  let release
  const attempt = { validate: () => new Promise(resolve => { release = resolve }), payload: () => ({ amount: '1' }), send: async body => { calls.push(body); return { data: { id: 1 } } } }
  const first = command.run(attempt), second = await command.run(attempt)
  assert.equal(second.busy, true)
  release(true); await first; assert.equal(calls.length, 1)
  await command.run({ ...attempt, validate: undefined, confirm: async () => { throw 'cancel' } })
  assert.equal(command.failure.value, ''); assert.equal(calls.length, 1)
})

function validDraft() {
  const form = makeOrderDraft({ id: 5, commerce_version: 7, local_customer_id: 2, sales_user_id: 3, currency: 'USD', invoice_no: 'LOCAL-5', local_commercial: { commercial_source: 'referral', is_new_deal: false, department_allocations: [{ department_id: 1, rate: '100' }] }, items: [{ id: 8, local_sku_id: 9, quantity: 2, price_per_piece: '4.1250', discount_amount: '-0.25' }] })
  return form
}
test('editing and amendment preserve stable line IDs, explicit false commercial flags and exact amounts', () => {
  const form = validDraft(), body = draftPayload(form)
  assert.equal(body.items[0].id, 8); assert.equal(body.items[0].price_per_piece, '4.1250')
  assert.equal(body.is_new_deal, false); assert.equal(body.expected_version, 7)
  assert.equal(money.orderPreview(form).total, '8.00')
  assert.throws(() => draftPayload(form, true), /原因/)
  form.reason = 'Approved correction'; const amended = draftPayload(form, true)
  assert.equal(amended.invoice_no, 'LOCAL-5'); assert.equal(amended.items[0].id, 8)
  form.department_allocations.push({ department_id: 1, rate: '1' }); assert.throws(() => draftPayload(form), /重复/)
})

test('invalid decimal input, positive discounts, overflowing totals and presale freight never reach write', () => {
  const form = validDraft(); form.items[0].discount_amount = '1'; assert.throws(() => draftPayload(form), /折扣/)
  form.items[0].discount_amount = '0'; form.items[0].quantity = 2147483647; form.items[0].price_per_piece = '99999999.9999'; assert.throws(() => draftPayload(form), /范围/)
  form.items[0].quantity = 1; form.items[0].price_per_piece = '5'; form.order_type = 'presale'; form.shipping_fee = '1'; assert.throws(() => draftPayload(form), /运费/)
})

const payment = { id: 1, version: 4, status: 'confirmed', currency: 'USD', available_amount: '10.00' }
const detail = { invoice: { id: 3, order_type: 'presale' }, items: [{ id: 4, kind: 'goods', currency: 'USD', remaining_amount: '15.00' }, { id: 5, kind: 'freight', currency: 'USD', remaining_amount: '4.00', settlement_id: 7 }], settlements: [{ id: 7, state: 'awaiting_payment' }, { id: 8, state: 'ready' }] }
test('allocation validates balances and requires the correct live presale batch, with deposit isolated', () => {
  const form = { invoice_id: 3, receivable_id: 4, amount: '10.01', business_date: '2026-10-03', purpose: 'ordinary', settlement_id: 7 }
  assert.throws(() => allocationPayload(form, payment, detail), /余额/)
  form.amount = '10'; form.settlement_id = 8; assert.throws(() => allocationPayload(form, payment, detail), /批次/)
  form.purpose = 'presale_deposit'; assert.equal(allocationPayload(form, payment, detail).settlement_id, null)
  form.receivable_id = 5; form.amount = '3'; assert.throws(() => allocationPayload(form, payment, detail), /首款/)
  form.purpose = 'ordinary'; form.settlement_id = 7
  assert.equal(allocationPayload(form, payment, detail).receivable_id, 5)
  form.invoice_id = 99; assert.throws(() => allocationPayload(form, payment, detail), /加载/)
})
