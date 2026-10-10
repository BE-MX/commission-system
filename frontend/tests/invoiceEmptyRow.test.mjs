import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyHairRow, buildInvoicePayload, emptyInvoiceForm, invoiceQuantityIssue } from '../src/views/invoice/composables/invoiceEditorState.js'
import { isBlankInvoiceLine } from '../src/views/invoice/composables/useInvoicePasteImport.js'

for (const production of [false, true]) {
  test(`${production ? 'production' : 'stock'} blank row leaves all editable values empty`, () => {
    const row = emptyHairRow(production)
    assert.equal(row.item_type, production ? 'custom' : 'stock')
    for (const field of ['product_name', 'product_display', 'model', 'color', 'length', 'net_weight_grams', 'curl']) {
      assert.equal(row[field], '', field)
    }
    for (const field of ['id', 'product_id', 'sku_id', 'custom_product_id', 'quantity', 'price_per_piece', 'discount_amount']) {
      assert.equal(row[field], null, field)
    }
    assert.equal(isBlankInvoiceLine(row), true)
    assert.equal(row.semifinished_enabled, false)
    assert.deepEqual(row.semifinished_plan, [])
    assert.equal(row._importBatchFingerprint, '')
    const payload = buildInvoicePayload({ ...emptyInvoiceForm(), items: [row] }, 0)
    assert.deepEqual(payload.items, [], 'an untouched placeholder is not an order item')
    assert.equal(row.quantity, null, 'unfilled quantity must not silently become 1 on save')
    assert.equal(invoiceQuantityIssue([row]), null)
  })
}

test('only untouched, unsaved hair placeholders are omitted; entered and persisted content survives', () => {
  const changes = [
    { id: 10 }, { product_id: 'P1' }, { sku_id: 2 }, { custom_product_id: 3 },
    { product_name: 'Product' }, { product_display: 'Product' }, { model: 'Model' },
    { color: 'Black' }, { length: '20' }, { net_weight_grams: '100g' }, { curl: 'Straight' },
    { quantity: 1 }, { quantity: 0 }, { quantity: NaN }, { price_per_piece: 0 },
    { discount_amount: 2 }, { discount_amount: NaN }, { total_price: 2 },
    { semifinished_enabled: true }, { semifinished_plan: [{ material_id: 1 }] },
    { _importBatchFingerprint: 'batch' }, { product_kind: 'accessory' },
  ]
  for (const change of changes) {
    const row = { ...emptyHairRow(), ...change }
    const payload = buildInvoicePayload({ ...emptyInvoiceForm(), items: [emptyHairRow(), row] }, 0)
    assert.equal(payload.items.length, 1, JSON.stringify(change))
    assert.equal(payload.items[0].quantity, row.quantity)
    if (!Number.isInteger(row.quantity) || row.quantity <= 0) {
      assert.equal(invoiceQuantityIssue([emptyHairRow(), row]).row, row)
    }
  }
})

test('new rows have independent options and material plans', () => {
  const first = emptyHairRow()
  const second = emptyHairRow()
  first.options.models.push('X')
  first.semifinished_plan.push({ material_id: 1 })
  assert.deepEqual(second.options.models, [])
  assert.deepEqual(second.semifinished_plan, [])
})
