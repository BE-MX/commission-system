import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { babelParse, parse } from '@vue/compiler-sfc'
import { isAmount, isEmail, isPhone, normalizeExpoPhone } from '../src/utils/validators.js'
import { normalisePhone } from '../src/views/expo/composables/expoPhone.js'
import { targetChanges } from '../src/views/battle-report/helpers.js'
import { validateActionDetails } from '../src/views/aftersales/aftersalesRules.js'
import { cents, validateAllocations } from '../src/views/receipt/batchReceiptState.js'

// Execute the real save handler, with network/feedback boundaries substituted.
// Parsing its declaration avoids copying the validation expression into tests.
function handler(path, name, dependencies) {
  const file = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const source = path.endsWith('.vue') ? parse(file).descriptor.scriptSetup.content : file
  let declaration
  function visit(node) {
    if (!node || typeof node !== 'object' || declaration) return
    if (node.type === 'FunctionDeclaration' && node.id?.name === name) { declaration = node; return }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit)
      else if (value?.type) visit(value)
    }
  }
  visit(babelParse(source, { sourceType: 'module' }))
  assert.ok(declaration, `${name} exists in ${path}`)
  return new Function(...Object.keys(dependencies), `let requestIdentity = null; ${source.slice(declaration.start, declaration.end)}; return ${name}`)(...Object.values(dependencies))
}

test('phone strategies keep mainland, international and kiosk business ranges separate', () => {
  for (const value of ['13800138000', '19900000000']) assert.equal(isPhone(value), true)
  for (const value of ['', null, '12345678901', '+8613800138000', '+1 (415) 555-2671', '1380013800']) assert.equal(isPhone(value), false)
  assert.equal(isPhone('', { allowEmpty: true }), true)
  assert.equal(isPhone('12345678901', { strategy: 'expo-digits' }), true, 'kiosk requires eleven digits, not a mobile prefix')
  for (const value of ['+1 (415) 555-2671', '+44 20 7946 0958', '020-7946-0958', '+86 138 0013 8000']) {
    assert.equal(isPhone(value, { strategy: 'international' }), true)
  }
  for (const value of ['++14155552671', '555123', '+1234567890123456', 'call 14155552671', '123#456789']) {
    assert.equal(isPhone(value, { strategy: 'international' }), false)
  }
  assert.equal(isPhone('13800138000', { strategy: 'unknown' }), false)
})

test('real kiosk normalization preserves formatting, fullwidth, 86 and legacy eleven-digit policy', () => {
  for (const value of ['13800138000', '138 0013 8000', '138-0013-8000', '+86 138 0013 8000', '１３８００１３８０００']) {
    assert.equal(normalisePhone(value), '13800138000')
    assert.equal(normalizeExpoPhone(value), '13800138000')
  }
  assert.equal(normalisePhone('12345678901'), '12345678901')
  // Removing all non-digits is the established kiosk/backend contract.
  assert.equal(normalisePhone('phone: 13800138000'), '13800138000')
  for (const value of ['', null, undefined, '1380013800', '+44 20 7946 0958', '008613800138000', 'abcdef']) {
    assert.equal(normalisePhone(value), '')
  }
})

test('email basic shape supports plus tags and international domains without conflating requiredness', () => {
  for (const value of ['user@example.com', ' user+sales@example.co.uk ', '用户@例子.公司']) assert.equal(isEmail(value), true)
  for (const value of ['', null, undefined, '@example.com', 'user@', 'user@example', 'user name@example.com', 'a@@example.com', 'a@example.com\nsecond']) {
    assert.equal(isEmail(value), false)
  }
  assert.equal(isEmail('', { allowEmpty: true }), true)
  assert.equal(isEmail('wrong', { allowEmpty: true }), false)
})

test('decimal amount defaults distinguish empty, zero, signs, precision and format', () => {
  for (const value of ['1', '01.20', '0.01', 1, 0.1, ' 12.30 ']) assert.equal(isAmount(value), true)
  for (const value of ['', ' ', null, undefined, false, {}, [], 0, '0.00', '-1', '-0', '1.001', '1.', '.5', '1e3', '1,000', '+1', NaN, Infinity, 'Infinity']) {
    assert.equal(isAmount(value), false, String(value))
  }
  assert.equal(isAmount('', { allowEmpty: true }), true)
  assert.equal(isAmount('0', { allowZero: true }), true)
  assert.equal(isAmount('-1.25', { allowNegative: true }), true)
  assert.equal(isAmount('-0', { allowNegative: true, allowZero: true }), true)
  assert.equal(isAmount('12.30', { precision: 1 }), false)
  assert.equal(isAmount('12', { precision: 0 }), true)
  assert.equal(isAmount('12.0', { precision: 0 }), false)
  assert.equal(isAmount('0.0001', { precision: 4 }), true)
  assert.equal(isAmount('0.00001', { precision: null }), true)
  assert.equal(isAmount(' 1 ', { trim: false }), false)
  assert.equal(isAmount('1', { precision: -1 }), false)
  assert.equal(isAmount('1', { maxIntegerDigits: 0 }), false)
})

test('amount strategies retain fourteen-digit targets and unrestricted numeric control precision', () => {
  const targetPolicy = { maxIntegerDigits: 14, precision: 2 }
  assert.equal(isAmount('99999999999999.99', targetPolicy), true)
  assert.equal(isAmount('100000000000000.00', targetPolicy), false)
  assert.equal(isAmount('000000000000001', targetPolicy), false, 'integer limit counts typed digits')
  for (const value of [1.2345, '1.2345', '1e3', ' 10 ', '0x10']) assert.equal(isAmount(value, { format: 'number' }), true)
  for (const value of [0, -1, '', null, NaN, Infinity, 'invalid']) assert.equal(isAmount(value, { format: 'number' }), false)
  assert.equal(isAmount(0, { format: 'number', allowZero: true }), true)
})

test('real target validation preserves error text, trimming, leading zeros and exact one-cent changes', () => {
  const member = { id: 7, version: 2, user_name: 'A', can_edit: true, target_usd: '99999999999999.01' }
  assert.deepEqual(targetChanges([member], { 7: ' 99999999999999.02 ' }), [{ member_id: 7, version: 2, target_usd: '99999999999999.02' }])
  assert.deepEqual(targetChanges([{ ...member, target_usd: '10.00' }], { 7: '010' }), [])
  for (const value of ['0', '-1', '', '1.001', '1e6', '100000000000000']) {
    assert.throws(() => targetChanges([member], { 7: value }), { message: 'A：目标须为正数，最多两位小数' })
  }
  assert.deepEqual(targetChanges([{ ...member, target_usd: null }], { 7: '' }), [])
})

test('real aftersales monetary validation keeps four-decimal costs and discount-percent alternative', () => {
  assert.equal(validateActionDetails([{ code: 'cash_refund', amount_usd: '1.2345', currency: 'USD' }]), '')
  for (const value of ['', null, 0, -1, NaN, Infinity]) {
    assert.equal(validateActionDetails([{ code: 'cash_refund', amount_usd: value, currency: 'USD' }]), '退款金额必须大于 0')
  }
  assert.equal(validateActionDetails([{ code: 'discount', amount_usd: 0, discount_percent: 1, applicable_order: 'SO-1' }]), '')
  assert.equal(validateActionDetails([{ code: 'discount', amount_usd: '0.001', discount_percent: 0, applicable_order: 'SO-1' }]), '')
})

test('real recharge, base-price, special-sale and accessory-price saves retain messages and numeric precision', async () => {
  const cases = [
    ['views/domestic/composables/useDomesticCustomers.js', 'confirmRecharge', '请输入充值金额', (amount, effects) => ({
      rechargeDialog: { amount, customer: { id: 1 }, voucherFile: {}, requestId: 'one' },
      rechargeCustomer: async (_, payload) => { effects.push(payload.amount); return { data: {} } },
      fetchList: async () => {},
    })],
    ['views/domestic/DomesticProducts.vue', 'savePrice', '请填写大于 0 的原始价', (amount, effects) => ({
      priceDialog: { originalPrice: amount, impact: {}, product: { id: 1 } }, saving: { value: false },
      priceImpactLabel: () => 'one SKU', confirmAction: async () => {},
      updateProductBasePrice: async (_, value) => { effects.push(value); return { data: {} } }, fetchList: async () => {},
    })],
    ['views/domestic/components/DomesticDraftItemDialog.vue', 'save', '请填写销售价', (amount, effects) => ({
      busy: { value: false }, quoteLoading: { value: false }, saving: { value: false },
      special: { value: true }, production: { value: false }, props: { order: { id: 1, order_kind: 'business' } },
      item: { attrs: {}, order_qty: 1, specialPrice: amount }, validateItemAttributes: () => '',
      content: () => ({ special_price: amount }), ensureRequestIdentity: () => ({ requestId: 'one' }), makeRequestId: () => 'one',
      addDraftOrderItem: async (_, payload) => { effects.push(payload.special_price); return { data: {} } },
      emit: () => {}, quoteChangedDetail: () => null,
    })],
    ['views/invoice/components/AccessoryPriceConfig.vue', 'saveRow', '请输入有效的标准价', (amount, effects) => ({
      dialog: { candidate: {}, form: { product_id: 1, sku_id: 2, currency: 'USD', price: amount } }, saving: { value: false },
      saveAccessoryPriceForm: async ({ form, onSuccess }) => { effects.push(form.price); await onSuccess() },
      saveAccessoryPrice: async () => {}, loadRows: async () => {}, shouldShowAccessoryLocalError: () => false,
    })],
  ]
  for (const [path, name, message, dependencies] of cases) {
    for (const amount of [null, '', 0, -1, NaN, Infinity, 1.2345]) {
      const effects = [], warnings = []
      const warn = value => warnings.push(value)
      const save = handler(path, name, {
        isAmount, msgWarning: warn, ElMessage: { warning: warn, success() {} },
        msgSuccess: () => {}, msgSuccessText: () => {}, msgError: () => {},
        ...dependencies(amount, effects),
      })
      await save()
      if (amount === 1.2345) {
        assert.deepEqual(effects, [amount], path)
        assert.deepEqual(warnings, [], path)
      } else {
        assert.deepEqual(effects, [], path)
        assert.deepEqual(warnings, [message], path)
      }
    }
  }
})

test('receipt cents remains a domain parser with exact allocation equality and safe integer limits', () => {
  assert.equal(cents('0.10'), 10)
  assert.equal(cents('90071992547409.91'), Number.MAX_SAFE_INTEGER)
  assert.equal(cents('90071992547409.92'), null)
  for (const value of [' 1.00 ', '-1', '1.001', '1e3']) assert.equal(cents(value), null)
  const row = (id, amount) => ({ id, amount, customer_id: 'one', currency: 'USD', balance: { remaining_amount: '1.00', version: 1 } })
  assert.equal(validateAllocations([row(1, '0.10'), row(2, '0.20')], '0.30'), '')
  assert.equal(validateAllocations([row(1, '0.10'), row(2, '0.20')], '0.31'), '分配金额合计必须与本次回款总金额完全一致')
})
