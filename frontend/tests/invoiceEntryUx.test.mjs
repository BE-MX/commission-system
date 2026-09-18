import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, reactive, computed } from 'vue'
import { normalizeHairRow } from '../src/views/invoice/composables/invoiceEditorState.js'
import { calculateLineTotal } from '../src/views/invoice/composables/invoiceSettlement.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const hairSource = read('../src/views/invoice/composables/useInvoiceHairItems.js')
  .replace(/^import[\s\S]*?from ['"].*?['"]\r?\n/gm, '').replace('export function', 'function')
const hairFactory = new Function('normalizeHairRow', 'calculateLineTotal', `${hairSource}; return useInvoiceHairItems`)
for (const item_type of ['stock', 'custom']) {
  test(`copy ${item_type} retains edited customer price and recalculates amount`, () => {
    const original = normalizeHairRow({ id: 7, item_type, quantity: 3, price_per_piece: 12.3456,
      customer_price: 20, price_source: 'manual', discount_amount: -2, total_price: 999,
      semifinished_plan: [{ material_id: 1, quantity_grams: 10 }] })
    const form = { items: [original, { product_kind: 'accessory', price_per_piece: 1 }] }
    const api = hairFactory(normalizeHairRow, calculateLineTotal)(form, { value: [original] }, { value: item_type === 'custom' }, {})
    api.copyLine()
    const copied = form.items.at(-1)
    assert.equal(copied.id, null)
    assert.equal(copied.price_per_piece, 12.3456)
    assert.equal(copied.customer_price, 20)
    assert.equal(copied.price_source, 'manual')
    assert.equal(copied.total_price, 35.04)
    copied.semifinished_plan[0].quantity_grams = 20
    assert.equal(original.semifinished_plan[0].quantity_grams, 10)
  })
}

const uploadSource = read('../src/components/AppUpload.vue').match(/<script setup>([\s\S]*?)<\/script>/)[1]
  .replace(/^import .*\r?\n/gm, '')
function uploadHarness(overrides = {}) {
  const uploads = [], errors = []
  const props = { transfer: true, accept: 'image/png,image/jpeg,image/webp', maxSizeMb: 10,
    limit: 5, modelValue: [], uploadFn: async file => { uploads.push(file); return { path: file.name } }, ...overrides }
  const api = new Function('defineProps', 'defineEmits', 'ref', 'reactive', 'computed', 'msgError',
    `${uploadSource}; return { onDrop, onPaste, inflight, beforeUpload }`)(
    () => props, () => () => {}, ref, reactive, computed, message => errors.push(message))
  return { ...api, uploads, errors }
}
const picture = (type = 'image/png', size = 10) => ({ name: 'proof.png', type, size })
test('drop and clipboard files use upload and release progress slots', async () => {
  const h = uploadHarness()
  let prevented = 0
  await h.onDrop({ preventDefault: () => prevented++, dataTransfer: { files: [picture()] } })
  await h.onPaste({ preventDefault: () => prevented++, clipboardData: { items: [
    { kind: 'file', getAsFile: () => picture('image/jpeg') },
  ] } })
  assert.equal(prevented, 2)
  assert.equal(h.uploads.length, 2)
  assert.equal(h.inflight.value.length, 0)
})
test('batch rejects unsupported, oversized and excess images including pending uploads', async () => {
  const h = uploadHarness({ modelValue: [{ path: 'existing.png' }] })
  await h.onDrop({ preventDefault() {}, dataTransfer: { files: [picture('text/plain'),
    picture('image/png', 11 * 1024 * 1024), ...Array.from({ length: 6 }, () => picture())] } })
  assert.equal(h.uploads.length, 4)
  assert.equal(h.errors.length, 4)
})
test('ordinary text paste and disabled transfer are left untouched', async () => {
  const fail = () => assert.fail('must not consume event')
  const h = uploadHarness()
  await h.onPaste({ preventDefault: fail, clipboardData: { items: [{ kind: 'string' }] } })
  const disabled = uploadHarness({ transfer: false })
  await disabled.onDrop({ preventDefault: fail, dataTransfer: { files: [picture()] } })
  assert.equal(disabled.uploads.length, 0)
})
test('file picker reserves slots before async requests begin, including mixed paste input', async () => {
  const h = uploadHarness({ modelValue: [{ path: 'existing.png' }] })
  for (let i = 0; i < 4; i++) assert.equal(h.beforeUpload(picture()), true)
  assert.equal(h.beforeUpload(picture()), false)
  await h.onDrop({ preventDefault() {}, dataTransfer: { files: [picture()] } })
  assert.equal(h.uploads.length, 0)
})
test('failed upload reports an error and releases its slot for retry', async () => {
  const h = uploadHarness({ uploadFn: async () => { throw new Error('offline') } })
  await h.onDrop({ preventDefault() {}, dataTransfer: { files: [picture()] } })
  assert.equal(h.errors.length, 1)
  assert.equal(h.inflight.value.length, 0)
})
