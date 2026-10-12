import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeHairRow, buildInvoicePayload, isInvoicePlaceholder } from '../src/views/invoice/composables/invoiceEditorState.js'
import { normalizeAccessoryRow } from '../src/views/invoice/composables/accessoryPricing.js'
import { calculateInvoiceTotal, sumLineNet } from '../src/views/invoice/composables/invoiceSettlement.js'
import { mapPreviewRowToInvoiceLine } from '../src/views/invoice/composables/useInvoicePasteImport.js'

test('zero prices survive editing, totals and save payload for hair and accessories', () => {
  const hair = normalizeHairRow({ id: 1, quantity: 3, price_per_piece: 0, total_price: 0 })
  const accessory = normalizeAccessoryRow({ id: 2, quantity: 4, price_per_piece: 0, total_price: 0 })
  assert.equal(hair.price_per_piece, 0)
  assert.equal(accessory.price_per_piece, 0)
  assert.equal(isInvoicePlaceholder(hair), false)
  const form = { items: [hair, accessory], shipping_fee: 5 }
  const payload = buildInvoicePayload(form, 0)
  assert.deepEqual(payload.items.map(row => [row.quantity, row.price_per_piece]), [[3, 0], [4, 0]])
  assert.equal(calculateInvoiceTotal(sumLineNet(form.items), 0, form.shipping_fee, 0), 5)
})

test('paste preview keeps the explicitly supplied zero instead of customer reference price', () => {
  const row = mapPreviewRowToInvoiceLine({
    normalized: { product: 'Hair', color: 'Black', length: '18', weight: '100g', quantity: 2, unit_price: '0' },
    product: { product_id: 1, sku_id: 2, product_name: 'Hair' },
    customer_price: 15, standard_price: 15,
  }, 'batch')
  assert.equal(row.price_per_piece, 0)
  assert.equal(row.total_price, 0)
})
