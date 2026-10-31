import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { newRequestKey } from '../src/utils/requestKey.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useCursorResource } from '../src/composables/useCursorResource.js'
import { productionActions, qualityLabels } from '../src/views/production/native/labels.js'

function evaluate(path, modules, returns, props, emit = () => {}) {
  let source = readFileSync(new URL(path, import.meta.url), 'utf8')
  source = source.match(/<script setup>([\s\S]*?)<\/script>/)?.[1] || source
  source = source.replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
    const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
    return `const ${declaration} = modules[${JSON.stringify(key)}];`
  }).replaceAll('export function ', 'function ')
  return new Function('modules', 'defineProps', 'defineEmits', `${source}\nreturn ${returns};`)(modules, () => props, () => emit)
}
const { useNativeCommand } = evaluate('../src/views/finance/native/useNativeCommand.js', {
  vue: Vue, '@/utils/requestKey': { newRequestKey }, '@/utils/errors': { errorMessage: error => error.message }, '@/utils/feedback': { isFeedbackCancelled: () => false },
}, '{ useNativeCommand }')
const flush = async () => { for (let n = 0; n < 8; n++) { await Vue.nextTick(); await Promise.resolve() } }
function action(t, operation, overrides = {}) {
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const props = Vue.reactive({ modelValue: false, item: { id: 7, local_version: 3, product_name: 'Hair' }, operation,
    supplies: [{ id: 2, production_item_id: 7, invoice_item_id: 21, quantity: 3, received_quantity: 0, released_quantity: 0 }], supply: { id: 2 }, receipt: { event_id: 90 } })
  const calls = [], emitted = []
  let serial = 0
  const api = { getNativeProductionReference: async () => ({ data: { warehouses: [{ id: 1 }] } }),
    getNativeSupplyOptions: async () => ({ data: { items: [{ invoice_item_id: 21 }, { invoice_item_id: 22 }], total: 2 } }),
    getNativeMaterialOptions: async () => ({ data: { items: [{ id: 4 }], total: 1 } }),
    actNativeProductionItem: async (...args) => { calls.push(args); return { data: { id: 1 } } },
    releaseNativeProductionSupply: async (...args) => { calls.push(args); return { data: { id: 2 } } },
    reverseNativeProductionReceipt: async (...args) => { calls.push(args); return { data: { id: 3 } } }, ...overrides }
  const state = scope.run(() => evaluate('../src/views/production/native/NativeProductionAction.vue', {
    vue: Vue, '@/api/nativeProduction': api, '@/composables/useAsyncResource': { useAsyncResource }, '@/composables/useCursorResource': { useCursorResource },
    '@/views/finance/native/useNativeCommand': { useNativeCommand: () => useNativeCommand(() => `request-${++serial}`) },
    '@/utils/feedback': { confirmDanger: async () => {}, msgSuccess() {} }, './labels': { productionActions, qualityLabels },
  }, '{ form, command, options, submit }', props, (...args) => emitted.push(args)))
  props.modelValue = true
  return { ...state, props, calls, emitted }
}

test('supply picker retains multiple invoice-line identities and sends versioned native command', async t => {
  const state = action(t, 'supplies'); await flush()
  assert.equal(state.options.items.value.length, 2)
  Object.assign(state.form.value, { reason: 'Planned', quantity: 2, invoice_item_id: 22 })
  await state.submit()
  assert.deepEqual(state.calls[0], [7, 'supplies', { expected_version: 3, reason: 'Planned', quantity: 2, invoice_item_id: 22, request_key: 'request-1' }])
})
test('warehouse acceptance validates distribution and excludes hidden allocations for quarantine', async t => {
  const state = action(t, 'receive'); await flush()
  Object.assign(state.form.value, { reason: 'Accepted', quantity: 1, warehouse_id: 1, allocations: { 2: 2 } })
  await state.submit(); assert.equal(state.calls.length, 0); assert.match(state.command.failure.value, /合计/)
  state.form.value.quality = 'quarantine'
  await state.submit()
  assert.deepEqual(state.calls[0][2].allocations, [])
  assert.equal(state.calls[0][2].quality, 'quarantine')
})
test('uncertain receipt reversal reuses original identity and emits saved only after confirmed response', async t => {
  const calls = []
  const state = action(t, 'reverse', { reverseNativeProductionReceipt: async (...args) => { calls.push(args); if (calls.length === 1) throw new Error('Response lost'); return { data: { id: 3 } } } })
  await flush(); state.form.value.reason = 'Wrong warehouse'
  await state.submit(); assert.equal(state.emitted.length, 0)
  await state.submit()
  assert.equal(calls[0][0], 90); assert.deepEqual(calls[0], calls[1])
  assert.equal(state.emitted.filter(entry => entry[0] === 'saved').length, 1)
})
test('gram input rejects exponent and fourth decimal before material write', async t => {
  const state = action(t, 'loss'); await flush()
  Object.assign(state.form.value, { material_id: 4, quantity_grams: '1e2', reason: 'Measured' })
  await state.submit(); assert.equal(state.calls.length, 0)
  state.form.value.quantity_grams = '0.0001'; await state.submit(); assert.equal(state.calls.length, 0)
  state.form.value.quantity_grams = '1.125'; await state.submit()
  assert.equal(state.calls[0][1], 'materials/loss'); assert.equal(state.calls[0][2].quantity_grams, '1.125')
})

test('lost allocated receipt survives close, live version/quantity refresh and reopen with identical body', async t => {
  const calls = []
  const state = action(t, 'receive', { actNativeProductionItem: async (...args) => { calls.push(args); if (calls.length === 1) throw new Error('Response lost'); return { data: { id: 1 } } } })
  await flush(); Object.assign(state.form.value, { reason: 'Physical receipt A', quantity: 3, warehouse_id: 1, allocations: { 2: 3 } })
  await state.submit()
  state.props.modelValue = false; await flush()
  state.props.item.local_version = 4; state.props.supplies[0].received_quantity = 3
  state.props.modelValue = true; await flush()
  assert.equal(state.form.value.quantity, 3); assert.equal(state.form.value.expected_version, 3)
  assert.equal(state.command.failure.value, 'Response lost')
  await state.submit(); assert.deepEqual(calls[0], calls[1]); assert.equal(calls[1][2].allocations[0].quantity, 3)
})

test('supply pagination appends distinct invoice IDs', async t => {
  const state = action(t, 'supplies', { getNativeSupplyOptions: async params => ({ data: { items: [{ invoice_item_id: params.page * 10 }, { invoice_item_id: params.page * 10 + 1 }], total: 100 } }) })
  await flush(); await state.options.load({ item_id: 7, kind: 'supply', keyword: '' })
  assert.deepEqual(state.options.items.value.map(row => row.invoice_item_id), [10, 11, 20, 21])
})

test('pending creation rejects row changes and reopening preserves failed draft and identity', async t => {
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const props = Vue.reactive({ modelValue: false }), calls = []
  let rejectRequest, serial = 0
  const state = scope.run(() => evaluate('../src/views/production/native/NativeProductionEditor.vue', {
    vue: Vue, '@/views/inventory/components/SkuPicker.vue': { default: {} },
    '@/api/nativeProduction': { getNativeProductionReference: async () => ({ data: {} }), createNativeProduction: async body => { calls.push(body); if (calls.length === 1) return new Promise((_, reject) => { rejectRequest = reject }); return { data: { id: 1 } } } },
    '@/composables/useAsyncResource': { useAsyncResource }, '@/views/finance/native/useNativeCommand': { useNativeCommand: () => useNativeCommand(() => `create-${++serial}`) }, '@/utils/feedback': { msgSuccess() {} },
  }, '{ form, command, addLine, removeLine, submit }', props))
  props.modelValue = true; await flush()
  Object.assign(state.form.value, { batch_no: 'Batch A' }); state.form.value.items[0].local_sku_id = 1; state.addLine(); state.form.value.items[1].local_sku_id = 2
  const first = state.submit(); await flush()
  state.addLine(); state.removeLine(0); assert.equal(state.form.value.items.length, 2)
  rejectRequest(new Error('Response lost')); await first
  props.modelValue = false; await flush(); props.modelValue = true; await flush()
  assert.equal(state.form.value.batch_no, 'Batch A'); assert.equal(state.form.value.items.length, 2)
  await state.submit(); assert.deepEqual(calls[0], calls[1]); assert.equal(state.form.value.items.length, 0)
})
