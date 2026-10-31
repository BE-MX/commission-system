import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { qualityLabels } from '../src/views/inventory/labels.js'

const source = readFileSync(new URL('../src/views/inventory/components/StockDocumentEditor.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'stock-command-test' }).content
  .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
    const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
    return `const ${declaration} = modules[${JSON.stringify(key)}];`
  }).replace('export default', 'return')
const tick = async () => { await Vue.nextTick(); await Vue.nextTick() }
function editor(t, overrides = {}) {
  const calls = [], events = [], errors = []
  const api = {
    getWarehouses: async () => ({ data: [] }),
    getBalances: async () => ({ data: [{ quality: 'sellable', version: 8, on_hand: 12 }, { quality: 'quarantine', version: 3, on_hand: 4 }] }),
    postDocument: async body => { calls.push(structuredClone(body)); throw new Error('Response lost after request') }, ...overrides,
  }
  const component = new Function('modules', compiled)({
    vue: Vue, '@/api/inventory': api,
    '@/composables/useAsyncResource': { useAsyncResource },
    '@/utils/feedback': { msgSuccess() {}, msgError: message => errors.push(message) },
    '@/utils/errors': { errorMessage: error => error.message },
    './SkuPicker.vue': { default: {} }, '../labels': { qualityLabels },
  })
  const scope = Vue.effectScope()
  const state = scope.run(() => component.setup(Vue.reactive({ modelValue: true }), { expose() {}, emit: (...args) => events.push(args) }))
  t.after(() => scope.stop())
  state.formRef.value = { validate: async () => true }
  state.form.value.reason = 'Verified stock receipt'
  Object.assign(state.form.value.lines[0], { warehouse_id: 2, sku_id: 5, quantity: 3 })
  return { state, calls, events, errors }
}

test('stock retry keeps its command key; editing a quantity creates a new identity', async t => {
  const { state, calls } = editor(t)
  await state.save(); await state.save()
  assert.equal(calls.length, 2)
  assert.equal(calls[0].idempotency_key, calls[1].idempotency_key)
  state.form.value.lines[0].quantity = 4
  await state.save()
  assert.notEqual(calls[1].idempotency_key, calls[2].idempotency_key)
  assert.equal(calls[2].lines[0].quantity, 4)
})

test('repeated submit during asynchronous form validation sends only one command', async t => {
  const { state, calls } = editor(t)
  const releases = []
  state.formRef.value.validate = () => new Promise(resolve => { releases.push(resolve) })
  const first = state.save()
  const second = state.save()
  releases.forEach(release => release(true))
  await Promise.all([first, second])
  assert.equal(calls.length, 1)
})

test('count requires a fresh observation and submits the selected quality version', async t => {
  const { state, calls, errors } = editor(t)
  state.form.value.kind = 'count'
  state.form.value.lines[0].quality = 'quarantine'
  await state.save()
  assert.equal(calls.length, 0)
  assert.match(errors.at(-1), /读取/)
  await state.readVersions()
  await state.save()
  assert.equal(calls[0].lines[0].expected_version, 3)
  assert.equal(calls[0].lines[0].quality, 'quarantine')
  assert.equal(calls[0].lines[0].quantity, 3)
})

test('a changed stock dimension discards an in-flight count observation', async t => {
  let release
  const { state, errors } = editor(t, { getBalances: () => new Promise(resolve => { release = resolve }) })
  state.form.value.kind = 'count'
  const request = state.readVersions()
  state.form.value.lines[0].sku_id = 6
  release({ data: [{ quality: 'sellable', version: 99, on_hand: 12 }] })
  await request; await tick()
  assert.equal(state.form.value.lines[0].expected_version, null)
  assert.match(errors.at(-1), /重新读取/)
})

test('duplicate inventory dimensions and same-warehouse transfer never post', async t => {
  const { state, calls } = editor(t)
  state.form.value.lines.push({ ...state.form.value.lines[0], key: 2 })
  await state.save(); assert.equal(calls.length, 0)
  state.form.value.lines.pop()
  state.form.value.kind = 'transfer'
  state.form.value.lines[0].destination_warehouse_id = 2
  await state.save(); assert.equal(calls.length, 0)
})
