import test from 'node:test'
import assert from 'node:assert/strict'
import { stockRows, shipmentQuantityLimit, shipmentStockError, fillShipmentQuantities } from '../src/views/invoice/composables/shipmentInventory.js'

const lines = () => [{ id: 7, product_id: 11, sku_id: 22, remaining: 10, requested: 0 },
  { id: 8, product_id: 11, sku_id: 22, remaining: 4, requested: 0 }]
const snapshot = (amount = '6.9') => ({ invoice_id: 1, source: 'okki_live', items: [7, 8].map(id => ({ invoice_item_id: id, product_id: '11', sku_id: '22', available_stock: amount })) })
test('integer cap floors live stock and respects remaining quantity', () => {
  const rows = lines(), stocks = stockRows(snapshot(), 1, rows)
  assert.equal(shipmentQuantityLimit(rows[0], stocks), 6)
  assert.equal(shipmentQuantityLimit(rows[1], stocks), 4)
  rows[0].requested = 7
  assert.match(shipmentStockError(rows, stocks), /不能超过/)
})
test('same SKU lines share stock and invalid refresh keeps original draft quantities', () => {
  const rows = lines(); rows[0].requested = 4; rows[1].requested = 3
  assert.match(shipmentStockError(rows, stockRows(snapshot('6'), 1, rows)), /合计超过/)
  assert.equal(shipmentStockError(rows, stockRows(snapshot('7'), 1, rows)), '')
  assert.match(shipmentStockError(rows, stockRows(snapshot(null), 1, rows)), /待核对/)
  assert.deepEqual(rows.map(row => row.requested), [4, 3])
})
test('unavailable, malformed, negative stock stays unknown; true zero is zero', () => {
  for (const amount of [null, '', true, 'NaN', 'Infinity', '-1', '9007199254740992', '1e3', '0x10']) {
    const rows = lines(), stocks = stockRows(snapshot(amount), 1, rows)
    assert.equal(stocks.get(7).available, null)
    assert.equal(shipmentQuantityLimit(rows[0], stocks), 0)
  }
  assert.equal(stockRows(snapshot('0'), 1, lines()).get(7).available, '0')
  const rows = lines(), stocks = stockRows(snapshot('0.99999999999999999999'), 1, rows)
  assert.equal(shipmentQuantityLimit(rows[0], stocks), 0)
})
test('foreign invoice, mirror, changed mapping and duplicate identities rejected', () => {
  const bad = [ { ...snapshot(), invoice_id: 2 }, { ...snapshot(), source: 'mirror' },
    { ...snapshot(), items: [{ ...snapshot().items[0], sku_id: 23 }] },
    { ...snapshot(), items: [snapshot().items[0], snapshot().items[0]] } ]
  for (const data of bad) assert.throws(() => stockRows(data, 1, lines()))
})

test('one click fills remaining quantities using a shared SKU budget in order', () => {
  const rows = lines(); rows[0].remaining = 3; rows[0].requested = 1; rows[1].requested = 4
  const stocks = stockRows(snapshot('6.9'), 1, rows), before = JSON.stringify(rows)
  assert.deepEqual(fillShipmentQuantities(rows, stocks), [3, 3])
  assert.equal(JSON.stringify(rows), before)
  assert.deepEqual(fillShipmentQuantities(rows, stockRows(snapshot('100'), 1, rows)), [3, 4])
})

test('fill skips unknown/zero/fractional stock, exhausted lines and inconsistent SKU facts', () => {
  const rows = lines()
  for (const amount of [null, '0', '0.99999999999999999999']) assert.deepEqual(fillShipmentQuantities(rows, stockRows(snapshot(amount), 1, rows)), [0, 0])
  rows[0].remaining = 0
  assert.deepEqual(fillShipmentQuantities(rows, stockRows(snapshot('3'), 1, rows)), [0, 3])
  const stocks = stockRows(snapshot('3'), 1, rows); stocks.get(8).limit = 4
  assert.deepEqual(fillShipmentQuantities(rows, stocks), [0, 0])
})
