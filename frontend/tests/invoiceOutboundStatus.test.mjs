import test from 'node:test'
import assert from 'node:assert/strict'

import * as stock from '../src/views/invoice/composables/useInvoiceStockShortage.js'


test('outbound presentation distinguishes allocated, partial, shipped and unknown', () => {
  assert.equal(typeof stock.invoiceOutboundStatus, 'function')
  const row = { id: 1, product_id: 8, sku_id: 9, quantity: 5 }
  const entry = { invoice_item_id: 1, product_id: 8, sku_id: 9, outbound_quantity: '5', shipped_quantity: '2', outbounds: [
    { id: 'OB-1', number: 'CK-1', state: 'shipped', quantity: '2' },
    { id: 'OB-2', number: 'CK-2', state: 'generated', quantity: '3' },
  ] }
  const partial = stock.invoiceOutboundStatus(row, { items: [entry] })
  assert.equal(partial.code, 'partial')
  assert.equal(partial.linked, true)
  assert.equal(partial.shipped, 2)
  assert.equal(partial.allocated, 5)
  assert.equal(partial.references.length, 2)
  assert.match(partial.label, /2\/5/)

  assert.equal(stock.invoiceOutboundStatus(row, { items: [{ ...entry, shipped_quantity: '5' }] }).code, 'shipped')
  assert.equal(stock.invoiceOutboundStatus(row, { items: [{ ...entry, shipped_quantity: '0' }] }).code, 'allocated')
  assert.equal(stock.invoiceOutboundStatus(row, { items: [{ ...entry, outbound_quantity: '0', shipped_quantity: '0', outbounds: [] }] }).code, 'none')
  assert.equal(stock.invoiceOutboundStatus(row, { items: [{ ...entry, outbound_quantity: null, shipped_quantity: null }] }).code, 'unknown')
  assert.equal(stock.invoiceOutboundStatus(row, null).code, 'unknown')
})

test('new or replaced lines never inherit another line outbound state', () => {
  const entry = { invoice_item_id: 1, product_id: 8, sku_id: 9, outbound_quantity: '5', shipped_quantity: '5', outbounds: [{ id: 'OB-1' }] }
  const snapshot = { items: [entry] }
  assert.equal(stock.invoiceOutboundStatus({ product_id: 8, sku_id: 9, quantity: 5 }, snapshot).code, 'none')
  assert.equal(stock.invoiceOutboundStatus({ id: 1, product_id: 8, sku_id: 10, quantity: 5 }, snapshot).code, 'unknown')
  assert.equal(stock.invoiceOutboundStatus({ id: 1, product_id: 8, sku_id: 10, quantity: 5 }, {
    items: [{ ...entry, outbound_quantity: '0', shipped_quantity: '0', outbounds: [] }],
  }).code, 'none')
})
