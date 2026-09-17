import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyHairRow, buildInvoicePayload, emptyInvoiceForm } from '../src/views/invoice/composables/invoiceEditorState.js'
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
    assert.equal(payload.items[0].quantity, null, 'unfilled quantity must not silently become 1 on save')
  })
}

test('new rows have independent options and material plans', () => {
  const first = emptyHairRow()
  const second = emptyHairRow()
  first.options.models.push('X')
  first.semifinished_plan.push({ material_id: 1 })
  assert.deepEqual(second.options.models, [])
  assert.deepEqual(second.semifinished_plan, [])
})
