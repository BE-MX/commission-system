import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { calculateLineTotal } from '../src/views/invoice/composables/invoiceSettlement.js'
import { emptyHairRow, emptyInvoiceForm, buildInvoicePayload, normalizeHairRow } from '../src/views/invoice/composables/invoiceEditorState.js'
import { hasImportedBatch, isBlankInvoiceLine, mapPreviewRowToInvoiceLine } from '../src/views/invoice/composables/useInvoicePasteImport.js'
import * as receiptState from '../src/views/invoice/composables/invoiceReceiptState.js'

const hairSource = readFileSync(new URL('../src/views/invoice/composables/useInvoiceHairItems.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"].*?['"]\r?\n/gm, '').replace('export function', 'function')
const hairFactory = new Function(
  'normalizeHairRow', 'emptyHairRow', 'calculateLineTotal', 'hasImportedBatch', 'isBlankInvoiceLine',
  'mapPreviewRowToInvoiceLine', 'msgWarning', 'msgInfo',
  `${hairSource}; return useInvoiceHairItems`,
)

function setup(form, targetKey, warnings = []) {
  return hairFactory(
    normalizeHairRow, emptyHairRow, calculateLineTotal, hasImportedBatch, isBlankInvoiceLine,
    mapPreviewRowToInvoiceLine, message => warnings.push(message), () => {},
  )(form, { value: form.items }, { value: false }, { value: {} }, {
    getTargetGroupKey: () => targetKey,
    getSourceItems: key => form.items.filter(row => row.product_kind !== 'accessory' && row.group_key === key),
  })
}

function preview(fingerprint = 'batch-1') {
  return [{
    normalized: { product: 'Imported', length: '18', color: '#1B', weight: '100g', quantity: 2, unit_price: 30 },
    matched_product: { product_id: 11, sku_id: 9011, product_name: 'Imported product' },
  }]
}

test('add and copy use the active group and copy only that group source line', () => {
  const first = normalizeHairRow({ id: 1, group_key: 'a', product_name: 'Wrong global last', quantity: 2 })
  const second = normalizeHairRow({ id: 2, group_key: 'b', product_name: 'Current group source', quantity: 3 })
  const form = { items: [second, first] }
  const api = setup(form, 'b')

  api.copyLine()
  const copied = form.items.at(-1)
  assert.equal(copied.product_name, 'Current group source')
  assert.equal(copied.group_key, 'b')
  assert.equal(copied.id, null)
  assert.equal(copied.created_at, null)

  assert.notEqual(api.addBlankLine(), false)
  assert.equal(form.items.at(-1).group_key, 'b')
})

test('all-items view has no implicit append target', () => {
  const form = { items: [] }
  const warnings = []
  const api = setup(form, null, warnings)

  assert.equal(api.addBlankLine(), false)
  assert.equal(api.copyLine(), false)
  assert.equal(api.appendImportedLines(preview(), 'batch-1'), false)
  assert.equal(form.items.length, 0)
  assert.ok(warnings.length >= 3)
})

test('Excel append assigns the target group and only yields blank rows in that group', () => {
  const blankA = { ...emptyHairRow(), group_key: 'a' }
  const blankB = { ...emptyHairRow(), group_key: 'b' }
  const touchedA = normalizeHairRow({ group_key: 'a', product_display: 'Touched' })
  const form = { items: [blankA, blankB, touchedA] }
  const api = setup(form, 'b')

  assert.equal(api.appendImportedLines(preview(), 'batch-1'), true)
  assert.equal(form.items.includes(blankA), true)
  assert.equal(form.items.includes(blankB), false)
  assert.equal(form.items.includes(touchedA), true)
  assert.equal(form.items.at(-1).group_key, 'b')

  const count = form.items.length
  assert.equal(api.appendImportedLines(preview(), 'batch-1'), false, 'another group cannot bypass whole-order duplicate detection')
  assert.equal(form.items.length, count)
})

test('payload persists groups while business signatures ignore only display changes', () => {
  const form = { ...emptyInvoiceForm(), item_groups: [{ key: 'a', name: '首批', sort_order: 1 }] }
  form.items = [normalizeHairRow({ group_key: 'a', product_display: 'Product', color: '#1B', quantity: 2 })]
  const payload = buildInvoicePayload(form, 0)

  assert.deepEqual(payload.item_groups, form.item_groups)
  assert.equal(payload.items[0].group_key, 'a')
  const renamed = structuredClone(payload)
  renamed.item_groups[0].name = '改名'
  assert.equal(receiptState.invoiceBusinessSignature(payload), receiptState.invoiceBusinessSignature(renamed))
  assert.equal(receiptState.invoiceOrderSignature(payload), receiptState.invoiceOrderSignature(renamed))

  const moved = structuredClone(payload)
  moved.items[0].group_key = 'another-group'
  assert.equal(receiptState.invoiceBusinessSignature(payload), receiptState.invoiceBusinessSignature(moved))
  const receiptChanged = structuredClone(payload)
  receiptChanged.receipt_draft = { amount: '10', attachment_ids: [] }
  assert.notEqual(receiptState.invoiceBusinessSignature(payload), receiptState.invoiceBusinessSignature(receiptChanged))
})
