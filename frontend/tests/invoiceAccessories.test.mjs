import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  accessoryDiscount,
  accessoryGross,
  accessoryNet,
  accessoryStandardPriceState,
  applyAccessorySelection,
  createLatestRequestGate,
  normalizeAccessoryRow,
  removeItemByReference,
} from '../src/views/invoice/composables/accessoryPricing.js'
import { buildInvoicePayload } from '../src/views/invoice/composables/invoiceEditorState.js'
import { createLatestAccessorySearch } from '../src/views/invoice/composables/accessoryPriceConfigState.js'
import {
  calculateBalance,
  calculateInvoiceTotal,
  sumLineDiscount,
  sumLineGross,
  sumLineNet,
} from '../src/views/invoice/composables/invoiceSettlement.js'

const priceConfig = readFileSync(
  new URL('../src/views/invoice/InvoicePriceConfig.vue', import.meta.url),
  'utf8',
)
const accessoryConfig = readFileSync(
  new URL('../src/views/invoice/components/AccessoryPriceConfig.vue', import.meta.url),
  'utf8',
)
const api = readFileSync(new URL('../src/api/invoice.js', import.meta.url), 'utf8')
const invoiceView = readFileSync(
  new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url),
  'utf8',
)
const accessoryTable = readFileSync(
  new URL('../src/views/invoice/components/InvoiceAccessoryTable.vue', import.meta.url),
  'utf8',
)
const invoiceEditor = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url),
  'utf8',
)
const accessoryState = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceAccessories.js', import.meta.url),
  'utf8',
)
const hairState = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceHairItems.js', import.meta.url),
  'utf8',
)
const editorState = readFileSync(
  new URL('../src/views/invoice/composables/invoiceEditorState.js', import.meta.url),
  'utf8',
)
const totalsFooter = readFileSync(
  new URL('../src/views/invoice/components/InvoiceTotalsFooter.vue', import.meta.url),
  'utf8',
)
const tokens = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8')

test('accessory calculations normalize discounts and avoid floating point drift', () => {
  const row = normalizeAccessoryRow({
    product_id: 104881553777436,
    sku_id: 104881553777819,
    accessory_name: 'Hair Gripper',
    accessory_model: '魔术贴',
    accessory_color: 'Hair Gripper',
    standard_price: '2.7500',
    customer_price: '2.7500',
    quantity: 10,
    discount_amount: 1,
  })
  assert.equal(row.product_kind, 'accessory')
  assert.equal(row.discount_amount, -1)
  assert.equal(row.total_price, 26.5)
  assert.equal(accessoryGross([row]), 27.5)
  assert.equal(accessoryDiscount([row]), -1)
  assert.equal(accessoryNet([row]), 26.5)
  assert.equal(normalizeAccessoryRow({ discount_amount: 0 }).discount_amount, 0)
  assert.equal(accessoryGross([{ quantity: 3, price_per_piece: 0.1 }]), 0.3)
})

test('accessory money rounds the extended row amount instead of rounding four-decimal unit price first', () => {
  const rows = [
    normalizeAccessoryRow({ quantity: 10, price_per_piece: 2.755, discount_amount: -1 }),
    normalizeAccessoryRow({ quantity: 3, price_per_piece: 0.335, discount_amount: -0.01 }),
  ]
  assert.equal(rows[0].total_price, 26.55)
  assert.equal(rows[1].total_price, 1)
  assert.equal(accessoryGross(rows), 28.56)
  assert.equal(accessoryDiscount(rows), -1.01)
  assert.equal(accessoryNet(rows), 27.55)
})

test('four-decimal customer price becomes the default transaction price without a manual marker', () => {
  const row = normalizeAccessoryRow({
    product_id: 1,
    sku_id: 2,
    accessory_name: 'Hair Gripper',
    standard_price: '12.3500',
    customer_price: '13.5850',
    quantity: 10,
  })
  assert.equal(row.standard_price, 12.35)
  assert.equal(row.customer_price, 13.585)
  assert.equal(row.price_per_piece, 13.585)
  assert.equal(row.total_price, 135.85)
  assert.equal(row.price_source, 'customer_rule')
})

test('selection validates customer context and deletion removes the exact row object from payload', () => {
  const hair = { id: 1, product_kind: 'hair', quantity: 1, price_per_piece: 10 }
  const accessory = normalizeAccessoryRow({ id: 2, quantity: 10 })
  const other = normalizeAccessoryRow({ id: 3, quantity: 1 })
  const items = [hair, accessory, other]
  const option = {
    _customer_id: 'C-2', _currency: 'USD', product_id: 11, sku_id: 22,
    accessory_name: 'Hair Gripper', accessory_model: 'Tape', accessory_color: 'Black',
    standard_price: '12.3500', customer_price: '13.5850',
  }

  assert.equal(applyAccessorySelection(accessory, option, 'C-1', 'USD'), false)
  assert.equal(accessory.product_id, null)
  assert.equal(applyAccessorySelection(accessory, option, 'C-2', 'EUR'), false)
  assert.equal(applyAccessorySelection(accessory, option, 'C-2', 'USD'), true)
  assert.equal(accessory.total_price, 135.85)
  assert.equal(accessory.price_source, 'customer_rule')
  assert.equal(removeItemByReference(items, accessory), true)
  assert.deepEqual(items.map(row => row.id), [1, 3])
  const payload = buildInvoicePayload({
    customer_id: 'C-2', customer_name: 'Customer', invoice_date: '2026-07-15',
    currency: 'USD', order_type: 'stock', items,
  }, 0)
  assert.deepEqual(payload.items.map(row => row.id), [1, 3])
})

test('hair and accessory summaries share per-line currency rounding and settlement payload totals', () => {
  const hair = [
    { quantity: 1, price_per_piece: 10.005, discount_amount: -0.01 },
    { quantity: 3, price_per_piece: 0.335, discount_amount: 0 },
  ]
  const accessories = [
    { quantity: 10, price_per_piece: 2.755, discount_amount: -1 },
  ]
  assert.equal(sumLineGross(hair), 11.02)
  assert.equal(sumLineDiscount(hair), -0.01)
  assert.equal(sumLineNet(hair), 11.01)
  assert.equal(sumLineGross(accessories), 27.55)
  assert.equal(sumLineNet(accessories), 26.55)

  const productTotal = sumLineNet([...hair, ...accessories])
  const total = calculateInvoiceTotal(productTotal, 1.01, 2.01, 0.01)
  const prepayment = 20.01
  const balance = calculateBalance(total, prepayment)
  const payload = buildInvoicePayload({
    invoice_no: 'ROUND-1', order_type: 'stock', customer_id: '88', customer_name: 'Test',
    invoice_date: '2026-07-15', currency: 'USD', internal_accessory: 1.01,
    shipping_fee: 2.01, surcharge_amount: 0.01, internal_received: prepayment,
    internal_balance: balance, items: [...hair, ...accessories],
  }, sumLineDiscount(hair))

  assert.equal(productTotal, 37.56)
  assert.equal(total, 40.59)
  assert.equal(balance, 20.58)
  assert.equal(payload.internal_received, 20.01)
  assert.equal(payload.internal_balance, 20.58)
  assert.equal(payload.internal_discount, -0.01)
  assert.match(invoiceEditor, /const formProductTotal = computed\(\(\) => sumLineNet\(form\.items\)\)/)
})

test('accessory repricing discards responses from an older customer or currency', () => {
  const gate = createLatestRequestGate()
  const oldCustomer = gate.issue('customer-a|USD')
  const currentCurrency = gate.issue('customer-b|EUR')
  assert.equal(gate.isCurrent(oldCustomer, 'customer-a|USD'), false)
  assert.equal(gate.isCurrent(currentCurrency, 'customer-b|EUR'), true)
  assert.equal(gate.isCurrent(currentCurrency, 'customer-b|USD'), false)
})

test('an older hair price response cannot overwrite or mark the current customer price as manual', () => {
  const gate = createLatestRequestGate()
  const row = { customer_price: 22, price_per_piece: 22, price_source: 'customer_rule' }
  const oldRequest = gate.issue('customer-a|product-1|black|18|100')
  const currentRequest = gate.issue('customer-b|product-1|black|18|100')
  const apply = (token, context, customerPrice) => {
    if (!gate.isCurrent(token, context)) return
    row.customer_price = customerPrice
    row.price_per_piece = customerPrice
    row.price_source = 'customer_rule'
  }
  apply(currentRequest, 'customer-b|product-1|black|18|100', 30)
  apply(oldRequest, 'customer-b|product-1|black|18|100', 20)
  assert.deepEqual(row, { customer_price: 30, price_per_piece: 30, price_source: 'customer_rule' })
  assert.match(hairState, /const linePriceGates = new WeakMap\(\)/)
  assert.match(hairState, /gate\.isCurrent\(token, linePriceContext\(row\)\)/)
})

test('changing customer immediately clears accessory options and rejects stale customer options', () => {
  const invalidation = accessoryState.match(/function invalidateCustomerContext\(\)\s*{([\s\S]*?)\n  }/)?.[1] || ''
  assert.match(invalidation, /searchGate\.invalidate\(\)/)
  assert.match(invalidation, /priceGate\.invalidate\(\)/)
  assert.match(invalidation, /accessoryOptions\.value = \[\]/)
  assert.match(invalidation, /accessoryLoading\.value = false/)
  assert.match(accessoryState, /_customer_id: customerId/)
  assert.match(accessoryState, /_currency: currency/)
  assert.match(accessoryState, /applyAccessorySelection\(row, option, form\.customer_id, form\.currency\)/)
  assert.match(invoiceEditor, /form\.customer_name = customer\?\.company_name \|\| ''\s*\n\s*accessories\.invalidateCustomerContext\(\)/)
  assert.match(accessoryState, /const token = searchGate\.issue\(pricingContext\(\)\)\s*\n\s*accessoryOptions\.value = \[\]/)
  assert.match(accessoryState, /catch\s*{[\s\S]*searchGate\.isCurrent\(token,[\s\S]*accessoryOptions\.value = \[\]/)
  assert.match(invoiceEditor, /async function onCurrencyChange\(\)[\s\S]*invalidateCustomerContext\(\)[\s\S]*refreshAccessoryPrices\(\)/)
})

test('invoice accessory lookups request active catalog rows without changing price configuration history', () => {
  const activeRequests = accessoryState.match(/listAccessoryPrices\(\{[\s\S]*?\}\)/g) || []
  assert.equal(activeRequests.length, 2)
  for (const request of activeRequests) {
    assert.match(request, /active_only: true/)
    assert.match(request, /currency/)
  }
  assert.doesNotMatch(accessoryConfig, /active_only:\s*true/)
})

test('invoice accessory entry exposes only configured real-identity columns', () => {
  for (const label of ['#', 'Name', 'Model', 'Color', '标准价', '客户价', 'Quantity', '折扣', 'TotalPrice', '操作']) {
    assert.match(accessoryTable, new RegExp(`label="${label.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')}"`))
  }
  assert.doesNotMatch(accessoryTable, /Length|Net Weight|Curl|展开选填列/)
  assert.doesNotMatch(accessoryTable, /align="center"/)
  assert.match(accessoryTable, /remote-method="searchOptions"/)
  assert.match(accessoryTable, /readonly/)
  assert.match(accessoryTable, /product_id/)
  assert.match(accessoryTable, /sku_id/)
  assert.doesNotMatch(accessoryTable, /\bclearable\b/)
  assert.match(accessoryTable, /\.accessory-line-table :deep\(\.el-input-number\)[^}]*width:\s*100%/s)
})

test('blank accessory rows stay neutral until a selected SKU becomes invalid', () => {
  assert.equal(accessoryStandardPriceState({}), 'empty')
  assert.equal(accessoryStandardPriceState({ product_id: 1, sku_id: 2 }), 'invalid')
  assert.equal(accessoryStandardPriceState({ product_id: 1, sku_id: 2, standard_price: 0 }), 'priced')
})

test('invoice editor splits and recombines hair and accessory items', () => {
  assert.match(accessoryState, /const hairItems = computed/)
  assert.match(accessoryState, /const accessoryItems = computed/)
  assert.match(editorState, /product_kind: line\.product_kind/)
  assert.match(invoiceView, /<InvoiceHairTable[\s\S]*:items="hairItems"/)
  assert.match(invoiceView, /<InvoiceAccessoryTable/)
})

test('invoice payload round-trips mixed rows and preserves accessory identity', () => {
  const payload = buildInvoicePayload({
    invoice_no: 'INV-1', order_type: 'stock', customer_id: '88', customer_name: 'Test',
    invoice_date: '2026-07-15', currency: 'USD', items: [
      { id: 1, product_kind: 'hair', item_type: 'stock', quantity: 1, price_per_piece: 100, discount_amount: -10 },
      { id: 2, product_kind: 'accessory', item_type: 'stock', product_id: 104881553777436,
        sku_id: 104881553777819, product_name: 'Hair Gripper', product_display: 'Hair Gripper',
        model: '魔术贴', color: 'Hair Gripper', quantity: 10, price_per_piece: 2.75, discount_amount: -1 },
    ],
  }, -10)
  assert.equal(payload.items.length, 2)
  assert.equal(payload.items[1].id, 2)
  assert.equal(payload.items[1].product_kind, 'accessory')
  assert.equal(payload.items[1].product_id, 104881553777436)
  assert.equal(payload.items[1].sku_id, 104881553777819)
  assert.equal(payload.items[1].length, undefined)
})

test('footer uses eight token-backed amount chips without new motion', () => {
  for (const kind of ['hair', 'hair-discount', 'accessory', 'accessory-discount', 'packaging', 'shipping', 'handling', 'total']) {
    assert.match(totalsFooter, new RegExp(`summary-chip ${kind}`))
    assert.match(tokens, new RegExp(`--invoice-summary-${kind}-fg:`))
    assert.match(tokens, new RegExp(`--invoice-summary-${kind}-bg:`))
    assert.match(totalsFooter, new RegExp(`--invoice-summary-${kind}-fg`))
  }
  assert.doesNotMatch(accessoryTable, /transition\s*:|animation\s*:|@keyframes/)
  assert.match(totalsFooter, /\.summary-chip[^}]*color:\s*var\(--text-secondary\)/)
  assert.match(totalsFooter, /\.summary-chip strong[^}]*color:\s*var\(--invoice-summary-fg\)/)
})

test('price configuration separates hair and accessory prices without duplicating shared panels', () => {
  assert.match(priceConfig, /label="头发价格"/)
  assert.match(priceConfig, /label="配件价格"/)
  assert.match(priceConfig, /<AccessoryPriceConfig\s*\/>/)
  assert.equal((priceConfig.match(/label="色型映射"/g) || []).length, 1)
  assert.equal((priceConfig.match(/label="客户价格规则"/g) || []).length, 1)
})

test('accessory price table only exposes its supported identity and pricing fields', () => {
  assert.match(accessoryConfig, /Hair ExtensionsTools Fee/)
  assert.match(accessoryConfig, /label="Name"/)
  assert.match(accessoryConfig, /label="Model"/)
  assert.match(accessoryConfig, /label="Color"/)
  assert.match(accessoryConfig, /label="标准价"/)
  assert.match(accessoryConfig, /class="list-table"/)
  assert.match(accessoryConfig, /\bborder\b/)
  assert.doesNotMatch(accessoryConfig, /Length|Net Weight|展开选填列/)
  assert.doesNotMatch(accessoryConfig, /align="center"/)
})

test('accessory price list separates currency and update time with bounded columns', () => {
  assert.match(accessoryConfig, /label="Name"[^>]*min-width="180"[^>]*max-width="320"/)
  assert.match(accessoryConfig, /label="Model"[^>]*min-width="150"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="Color"[^>]*min-width="150"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="标准价"[^>]*min-width="110"[^>]*max-width="150"/)
  assert.match(accessoryConfig, /label="币种"[^>]*min-width="90"[^>]*max-width="110"/)
  assert.match(accessoryConfig, /label="更新时间"[^>]*min-width="170"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="操作"[^>]*min-width="150"[^>]*max-width="190"[^>]*fixed="right"/)
  assert.doesNotMatch(accessoryConfig, /label="操作"[^>]*\swidth=/)
  assert.match(accessoryConfig, /formatDateTime\(row\.updated_at\)/)
  assert.match(accessoryConfig, /if \(!value\) return '—'/)
  assert.match(accessoryConfig, /Number\(row\.standard_price\)\.toFixed\(2\)/)
  assert.doesNotMatch(accessoryConfig, /row\.currency\s*}}\s*{{\s*formatPrice/)
})

test('accessory editor selects a real OKKI product and SKU and keeps its snapshot readonly', () => {
  assert.match(accessoryConfig, /remote-method="searchCandidates"/)
  assert.match(accessoryConfig, /product_id/)
  assert.match(accessoryConfig, /sku_id/)
  const priceInput = accessoryConfig.match(/<el-input-number[^>]*v-model="dialog\.form\.price"[^>]*>/s)?.[0]
  assert.ok(priceInput, 'standard price input should exist')
  assert.match(priceInput, /:min="0\.01"/)
  assert.match(priceInput, /:precision="2"/)
  assert.match(priceInput, /:max="99999999\.99"/)
  assert.match(accessoryConfig, /Number\(form\.price\) <= 0/)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_name"[^>]*readonly/s)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_model"[^>]*readonly/s)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_color"[^>]*readonly/s)
})

test('accessory editor invalidates remote searches when opening or closing a dialog session', () => {
  assert.match(accessoryConfig, /@close="invalidateCandidateSearch"/)
  assert.match(accessoryConfig, /function openDialog\(row\)\s*{\s*invalidateCandidateSearch\(\)/)
  assert.match(accessoryConfig, /runCandidateSearch\.invalidate\(\)/)
})

test('accessory price list only applies the latest response and preserves rows on current failure', async () => {
  const pending = []
  const applied = []
  const loading = []
  const run = createLatestAccessorySearch({
    request: params => new Promise((resolve, reject) => pending.push({ params, resolve, reject })),
    applyItems: items => applied.push(items),
    applyLoading: value => loading.push(value),
    clearOnError: false,
  })

  const oldRequest = run({ keyword: 'old' })
  const newRequest = run({ keyword: 'new' })
  pending[1].resolve({ items: ['new'] })
  await newRequest
  pending[0].resolve({ items: ['old'] })
  await oldRequest
  assert.deepEqual(applied, [['new']])
  assert.equal(loading.at(-1), false)

  const failedRequest = run({ keyword: 'failed' })
  pending[2].reject(new Error('network'))
  await assert.rejects(failedRequest, /network/)
  assert.deepEqual(applied, [['new']])
})

test('accessory price screen routes list loading through the latest-request controller', () => {
  assert.match(accessoryConfig, /const runPriceList = createLatestAccessorySearch/)
  assert.match(accessoryConfig, /clearOnError:\s*false/)
  assert.match(accessoryConfig, /await runPriceList\(/)
})

test('invoice API exposes the complete accessory price lifecycle through the existing client', () => {
  assert.match(api, /export function searchAccessoryCandidates\(params\)/)
  assert.match(api, /request\.get\('\/price\/accessory-candidates'/)
  assert.match(api, /export function listAccessoryPrices\(params\)/)
  assert.match(api, /request\.get\('\/price\/accessories'/)
  assert.match(api, /export function saveAccessoryPrice\(data\)/)
  assert.match(api, /request\.post\('\/price\/accessories'/)
  assert.match(api, /export function deleteAccessoryPrice\(id\)/)
  assert.match(api, /request\.delete\(`\/price\/accessories\/\$\{id\}`\)/)
  assert.doesNotMatch(api, /axios\.create/)
})
