import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { reactive, ref, computed, watch, nextTick, effectScope } from 'vue'
import * as pricing from '../src/views/domestic/composables/domesticMemberPricing.js'
import * as attributes from '../src/views/domestic/domesticAttributeRules.js'
import * as kinds from '../src/views/domestic/domesticOrderKinds.js'
import { createLatestRequestRunner } from '../src/views/domestic/composables/latestRequest.js'

// Execute the real composable with Vue reactivity and boundary stubs, including
// the same cached instance when returning from a successful draft save.
const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticOrderCreate.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  .replace('export function useDomesticOrderCreate', 'function useDomesticOrderCreate')
const validAttrs = { product_type: 'cap', craft: '递旋', length: '20厘米', size: '59', hair_style_series: '直发' }

function harness(t, kind = 'business', overrides = {}) {
  const timers = new Map(), requests = [], created = [], navigations = []
  let serial = 0
  const scope = effectScope()
  const env = {
    reactive, ref, computed, watch, nextTick,
    ...pricing, ...attributes, ...kinds, createLatestRequestRunner,
    onMounted: () => {}, onBeforeUnmount: () => {},
    useRouter: () => ({ push: async value => navigations.push(value) }),
    currentBeijingDate: () => '2026-09-07', msgError: () => {},
    ElMessage: { warning() {}, info() {}, success() {} },
    ElMessageBox: { confirm: async () => {}, alert: async () => {} },
    setTimeout: callback => { timers.set(++serial, callback); return serial },
    clearTimeout: id => timers.delete(id),
    createOrder: async payload => { created.push(payload); return { data: { id: 1, domestic_no: 'DO20260907-001' } } },
    getOptions: async () => ({ data: {} }), listCustomers: async () => ({ data: { items: [] } }), uploadImage: async () => {},
    quoteDomesticPrices: async payload => {
      requests.push(payload)
      return { data: { items: payload.items.map(row => ({
        client_key: row.client_key, status: 'priced', original_price: 1000, discount_price: 900,
        expected_quote: { original_price: 1000, discount_price: 900, base_price_version: 1,
          membership_level: 'silver', pricing_rule: 'member_reduction', pricing_version: 'v1' },
      })) } }
    },
  }
  Object.assign(env, overrides)
  const factory = new Function(...Object.keys(env), `${source}; return useDomesticOrderCreate`)(...Object.values(env))
  const page = scope.run(() => factory(kind))
  t.after(() => scope.stop())
  Object.assign(page.form, { order_no: 'test-001', order_date: '2026-09-07', required_ship_date: '2026-09-10',
    customer_id: 7, order_type: 'first_order', order_channel: 'wechat' })
  Object.assign(page.form.items[0].attrs, validAttrs)
  page.customers.value = [{ id: 7, balance: 10000 }]
  async function settle() {
    await nextTick()
    for (const [id, callback] of [...timers]) { timers.delete(id); await callback() }
    await nextTick()
  }
  return { page, settle, requests, created, navigations }
}

test('adding an incomplete row preserves earlier manual price and quote', async t => {
  const { page, settle } = harness(t)
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  page.addItem()
  await settle()
  assert.equal(page.form.items[0].manualDiscountPrice, 850)
  assert.equal(page.form.items[0].quoteStatus, 'priced')
  assert.equal(page.form.items[1].quoteStatus, 'pending')
})

test('copy preserves both original and copied negotiated price without sharing objects', async t => {
  const { page, settle } = harness(t)
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  page.copyItem(0)
  await settle()
  assert.deepEqual(page.form.items.map(row => pricing.effectiveDiscountPrice(row)), [850, 850])
  assert.notEqual(page.form.items[0].key, page.form.items[1].key)
  page.form.items[1].attrs.length = '25厘米'
  await settle()
  assert.equal(page.form.items[0].manualDiscountPrice, 850)
  assert.equal(page.form.items[1].manualDiscountPrice, null)
})

test('valid rows quote independently while another row remains unfinished', async t => {
  const { page, settle, requests } = harness(t)
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  page.addItem()
  page.addItem()
  Object.assign(page.form.items[1].attrs, validAttrs)
  await settle()
  assert.equal(page.form.items[1].quoteStatus, 'priced')
  assert.equal(page.form.items[0].manualDiscountPrice, 850)
  assert.equal(requests.at(-1).items.length, 1)
})

test('customer change invalidates prior negotiated prices', async t => {
  const { page, settle } = harness(t)
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  page.form.customer_id = 8
  await settle()
  assert.equal(page.form.items[0].manualDiscountPrice, null)
})

test('successful draft save resets the cached new-order form and request identity', async t => {
  const { page, settle, created } = harness(t)
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  await page.submit(true)
  await settle()
  assert.equal(created.length, 1)
  assert.equal(created[0].items[0].manual_discount_price, 850)
  assert.equal(page.form.order_no, '')
  assert.equal(page.form.customer_id, null)
  assert.equal(page.form.items.length, 1)
  assert.equal(page.form.items[0].attrs.craft, '')
  assert.equal(page.form.items[0].manualDiscountPrice, null)
})

test('failed draft save preserves entered fields and manual prices for retry', async t => {
  const { page, settle, navigations } = harness(t, 'business', {
    createOrder: async () => { throw new Error('save failed') },
  })
  await settle()
  page.onManualPrice(page.form.items[0], 850)
  await page.submit(true)
  await settle()
  assert.equal(page.form.order_no, 'test-001')
  assert.equal(page.form.customer_id, 7)
  assert.equal(page.form.items[0].manualDiscountPrice, 850)
  assert.deepEqual(navigations, [])
})

test('customer order number is optional and channel defaults follow customer settlement mode', async t => {
  const { page, settle, created } = harness(t)
  await settle()
  assert.equal(page.form.order_channel, 'recharge')
  page.form.order_no = ''
  await page.submit(true)
  assert.equal(created.length, 1)
  assert.equal(created[0].order_no, '')
  page.customers.value = [{ id: 8, settle_mode: 'credit' }]
  page.form.customer_id = 8
  await settle()
  assert.equal(page.form.order_channel, 'cash')
  page.form.order_channel = 'recharge'
  page.customers.value = []
  await settle()
  page.customers.value = [{ id: 8, settle_mode: 'credit' }]
  await settle()
  assert.equal(page.form.order_channel, 'recharge')
})


test('business guest is trimmed in payload and cleared after successful save', async t => {
  const { page, settle, created } = harness(t)
  await settle()
  page.form.guest_name = '  王女士  '
  await page.submit(true)
  assert.equal(created[0].guest_name, '王女士')
  assert.equal(page.form.guest_name, '')
})
