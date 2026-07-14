import test from 'node:test'
import assert from 'node:assert/strict'

import {
  hasImportedBatch,
  mapPreviewRowToInvoiceLine,
  parseInvoiceClipboard,
} from '../src/views/invoice/composables/useInvoicePasteImport.js'


test('parses the standard six-column clipboard format', () => {
  const result = parseInvoiceClipboard([
    'Product\tLength\tColor\tWeight\tQuantity\tUnit Price',
    'Standard Double Drawn Genius Weft\t18\t#1B\t100g\t2\t36.00',
  ].join('\n'))

  assert.deepEqual(result.rows, [{
    source_row: 2,
    product: 'Standard Double Drawn Genius Weft',
    length: '18',
    color: '#1B',
    weight: '100g',
    quantity: '2',
    unit_price: '36.00',
  }])
  assert.deepEqual(result.ignoredHeaders, [])
})


test('prefers Product over the composed Product_name column in historical templates', () => {
  const result = parseInvoiceClipboard([
    'Product_name\tProduct\tNet Weight Grams\tLength\tColor\tQuantity\tPrice/Piece\tTotal',
    '组合产品名称\tStandard Double Drawn Genius Weft\t100g\t18\t#1B\t2\t36.00\t72.00',
  ].join('\n'))

  assert.equal(result.rows[0].product, 'Standard Double Drawn Genius Weft')
  assert.equal(result.rows[0].weight, '100g')
  assert.equal(result.rows[0].unit_price, '36.00')
  assert.deepEqual(result.ignoredHeaders, ['Product_name', 'Total'])
})


test('accepts six columns without a header and reports positional recognition', () => {
  const result = parseInvoiceClipboard(
    'Standard Double Drawn Genius Weft\t18\t#1B\t100g\t2\t36.00',
  )

  assert.equal(result.rows[0].source_row, 1)
  assert.match(result.warnings[0], /标准列顺序/)
})


test('ignores blank rows but rejects missing required headers and short rows', () => {
  const withBlanks = parseInvoiceClipboard([
    '',
    'Product\tLength\tColor\tWeight\tQuantity\tUnit Price',
    '',
    'Genius Weft\t18\t#1B\t100g\t1\t20',
    '',
  ].join('\n'))
  assert.equal(withBlanks.rows.length, 1)

  assert.throws(
    () => parseInvoiceClipboard('Product\tLength\tColor\nGenius Weft\t18\t#1B'),
    /缺少必填列/,
  )
  assert.throws(
    () => parseInvoiceClipboard('Product\tLength\tColor\tWeight\tQuantity\tUnit Price\nGenius Weft\t18'),
    /列数不足/,
  )
})


test('rejects batches over 200 rows', () => {
  const header = 'Product\tLength\tColor\tWeight\tQuantity\tUnit Price'
  const row = 'Genius Weft\t18\t#1B\t100g\t1\t20'
  assert.throws(() => parseInvoiceClipboard([header, ...Array(201).fill(row)].join('\n')), /最多导入 200 行/)
})


test('maps preview rows without losing the pasted transaction price', () => {
  const line = mapPreviewRowToInvoiceLine({
    normalized: {
      product: 'Genius Weft', length: '18', color: '#1B', weight: '100g',
      quantity: 2, unit_price: '34.00',
    },
    matched_product: {
      product_id: 11, sku_id: 9011, product_name: 'Genius Weft/18/#1B/100g',
    },
    price_source: 'manual',
    standard_price: '36.00',
    customer_price: '36.00',
  }, 'batch-1', 'stock')

  assert.equal(line.product_id, 11)
  assert.equal(line.price_per_piece, 34)
  assert.equal(line.price_source, 'manual')
  assert.equal(line._importBatchFingerprint, 'batch-1')
})


test('batch duplicate protection lasts only while a batch line remains', () => {
  const items = [{ _importBatchFingerprint: 'batch-1' }, { product_display: 'manual row' }]
  assert.equal(hasImportedBatch(items, 'batch-1'), true)
  assert.equal(hasImportedBatch(items.slice(1), 'batch-1'), false)
})
