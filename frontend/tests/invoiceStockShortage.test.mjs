import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { invoiceStockStatus, useInvoiceStockShortage } from '../src/views/invoice/composables/useInvoiceStockShortage.js'
import { buildInvoicePayload } from '../src/views/invoice/composables/invoiceEditorState.js'
import { sortTableRows } from '../src/utils/tableSort.js'

test('new lines compare exact available stock with all unshipped quantity, strictly less only', () => {
  for (const [available_stock, quantity, expected] of [[3, 4, true], [4, 4, false], [5, 4, false], [0, 1, true], [-1, 1, true], [0.9, 1, true]]) {
    assert.equal(invoiceStockStatus({ available_stock, quantity }).shortage, expected)
  }
  for (const available_stock of [null, undefined, '', ' ', false, NaN, Infinity, 'invalid']) {
    assert.equal(invoiceStockStatus({ available_stock, quantity: 10 }).shortage, false)
  }
})

test('saved lines deduct verified shipments by exact line identity, including repeated SKUs', () => {
  const row = { id: 1, product_id: 8, sku_id: 9, quantity: 10 }
  const snapshot = { items: [
    { invoice_item_id: 1, product_id: 8, sku_id: 9, available_stock: 4, shipped_quantity: '6' },
    { invoice_item_id: 2, product_id: 8, sku_id: 9, available_stock: 4, shipped_quantity: '0' },
  ] }
  assert.deepEqual(invoiceStockStatus(row, snapshot), { available: 4, remaining: 4, shortage: false })
  assert.equal(invoiceStockStatus({ ...row, id: 2 }, snapshot).shortage, true)
  assert.equal(invoiceStockStatus({ ...row, quantity: 11 }, snapshot).shortage, true)
  assert.equal(invoiceStockStatus({ ...row, quantity: 6 }, snapshot).shortage, false)
  const changed = { ...row, sku_id: 10, available_stock: 0 }
  assert.deepEqual(invoiceStockStatus(changed, snapshot), { available: 0, remaining: null, shortage: false })
  snapshot.items[0].shipped_quantity = '0'
  assert.deepEqual(invoiceStockStatus(changed, snapshot), { available: 0, remaining: 10, shortage: true }, 'saved draft can replace its SKU and immediately show the new stock shortage')
  assert.equal(invoiceStockStatus(row, null).shortage, false)
  snapshot.items[0].shipped_quantity = null
  assert.equal(invoiceStockStatus(row, snapshot).remaining, null)
})

test('filter retains original editable rows and payload, and reacts to quantity and stock', async t => {
  const props = Vue.reactive({ items: [{ product_id: 1, sku_id: 2, quantity: 5, available_stock: 3 },
    { product_id: 2, sku_id: 3, quantity: 2, available_stock: 8 }, { quantity: null }] })
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const state = scope.run(() => useInvoiceStockShortage(props, () => { throw new Error('new invoices need no saved inventory request') }))
  const before = buildInvoicePayload({ items: props.items }, 0)
  assert.equal(state.onlyShortage.value, false)
  state.onlyShortage.value = true
  assert.equal(state.filteredItems.value.length, 1)
  assert.equal(state.filteredItems.value[0], props.items[0])
  assert.deepEqual(buildInvoicePayload({ items: props.items }, 0), before)
  props.items[0].quantity = 3
  assert.equal(state.filteredItems.value.length, 0)
  props.items[0].available_stock = 0
  assert.equal(state.filteredItems.value.length, 1)
  props.items[0].available_stock = null
  assert.equal(state.filteredItems.value.length, 0)
  assert.equal(state.unknownCount.value, 1)
})

test('late saved-inventory responses cannot overwrite another invoice or closed editor', async t => {
  const props = Vue.reactive({ invoiceId: 1, active: true, items: [{ id: 1, product_id: 8, sku_id: 9, quantity: 10 }] })
  const pending = []
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const state = scope.run(() => useInvoiceStockShortage(props, id => new Promise(resolve => pending.push({ id, resolve }))))
  props.invoiceId = 2
  await Vue.nextTick()
  pending[1].resolve({ invoice_id: 2, items: [{ invoice_item_id: 1, product_id: 8, sku_id: 9, available_stock: 2, shipped_quantity: 1 }] })
  await Vue.nextTick(); await Vue.nextTick()
  assert.equal(state.stockStatus(props.items[0]).shortage, true)
  pending[0].resolve({ invoice_id: 1, items: [] })
  await Vue.nextTick()
  assert.equal(state.stockStatus(props.items[0]).shortage, true)
  const refresh = state.refreshInventory()
  props.active = false
  await Vue.nextTick()
  pending[2].resolve({ invoice_id: 2, items: [] })
  await refresh
  assert.equal(state.stockStatus(props.items[0]).available, null)
  assert.equal(state.loading.value, false)
})

const table = readFileSync(new URL('../src/views/invoice/components/InvoiceHairTable.vue', import.meta.url), 'utf8')

test('free stock is displayed while this order uses only its physically available reservation', () => {
  const row = { id: 1, product_id: 8, sku_id: 9, quantity: 10 }
  const entry = { invoice_item_id: 1, product_id: 8, sku_id: 9, available_stock: 0, order_available_stock: 10, shipped_quantity: '0' }
  assert.deepEqual(invoiceStockStatus(row, { items: [entry] }), { available: 0, remaining: 10, shortage: false })
  entry.order_available_stock = 6
  assert.deepEqual(invoiceStockStatus(row, { items: [entry] }), { available: 0, remaining: 10, shortage: true })
  assert.ok(table.includes('label="自由可用"'))
  assert.ok(!table.includes('label="可用库存 / 未发货"'))
})

test('shortage filtering compares total repeated SKU demand instead of each individual line', t => {
  const props = Vue.reactive({ items: [1, 2].map(() => ({ product_id: 8, sku_id: 9, quantity: 4, available_stock: 6 })) })
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const state = scope.run(() => useInvoiceStockShortage(props, () => {}))
  state.onlyShortage.value = true
  assert.equal(state.filteredItems.value.length, 2)
})
test('filter spans all pages, clears hidden selection and reveals invalid or newly added rows', async t => {
  const props = Vue.reactive({ items: Array.from({ length: 45 }, (_, index) => ({ id: null, product_id: index + 1,
    quantity: index + 2, available_stock: index % 2 ? 100 : 0 })) })
  const script = table.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g,
    (_, binding, key) => `const ${binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`} = modules[${JSON.stringify(key)}] || {};`)
  let cleared = 0
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const state = scope.run(() => new Function('modules', 'defineProps', 'defineEmits', `${script}\nreturn { page, pagedItems, onlyShortage, sortLines };`)(
    { vue: Vue, '@/utils/tableSort': { sortTableRows }, '../composables/useInvoiceStockShortage.js': { useInvoiceStockShortage },
      '../composables/useLineSelection.js': { useLineSelection: () => ({ selectedCount: Vue.ref(0), clearSelection() { cleared++ } }) } }, () => props, () => () => {}))
  state.page.value = 3
  state.onlyShortage.value = true
  await Vue.nextTick()
  assert.equal(state.page.value, 1)
  assert.equal(state.pagedItems.value.length, 20)
  assert.ok(cleared > 0)
  state.sortLines({ prop: 'quantity', order: 'descending' })
  assert.equal(state.pagedItems.value[0].product_id, 45)
  state.page.value = 2
  assert.equal(state.pagedItems.value.length, 3)
  for (const row of props.items) row.available_stock = 100
  await Vue.nextTick()
  assert.equal(state.page.value, 1)
  assert.equal(state.pagedItems.value.length, 0)
  props.quantityErrorRow = props.items[44]
  await Vue.nextTick(); await Vue.nextTick()
  assert.equal(state.onlyShortage.value, false)
  assert.equal(state.page.value, 3)
  assert.ok(state.pagedItems.value.includes(props.quantityErrorRow))
  state.onlyShortage.value = true
  props.items.push({ quantity: null })
  await Vue.nextTick()
  assert.equal(state.onlyShortage.value, false)
  assert.ok(state.pagedItems.value.includes(props.items.at(-1)))
})
