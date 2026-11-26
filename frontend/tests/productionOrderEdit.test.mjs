import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parseProductName } from '../src/utils/productName.js'
import { buildEditPayload, isLineChanged, payloadChangesItems } from '../src/views/stock/composables/productionOrderEditPayload.js'

const productSelect = readFileSync(
  new URL('../src/views/stock/components/ProductionOrderProductSelect.vue', import.meta.url),
  'utf8',
).replace(/\r\n/g, '\n')

test('splits hair product names into series, length, color and weight', () => {
  assert.deepEqual(parseProductName('Super Double Drawn Genius Weft/22/#P8/24/50g'), {
    raw: 'Super Double Drawn Genius Weft/22/#P8/24/50g',
    series: 'Super Double Drawn Genius Weft',
    length: '22',
    color: '#P8/24',
    weight: '50g',
  })
  assert.equal(parseProductName('Super Double Drawn Tape Hair/18/#2B/2.5g').color, '#2B')
  assert.equal(parseProductName('Super Double Drawn Genius Weft/24/Cookies Cream/20g').color, 'Cookies Cream')
})

test('falls back to the full name when the format is unknown', () => {
  assert.deepEqual(parseProductName('临时样品'), { raw: '临时样品', series: '临时样品', length: '', color: '', weight: '' })
  assert.equal(parseProductName(null).raw, '')
})

const order = { batch_no: 'B1', status: 0, remark: '', items_editable: true }
const form = { batch_no: 'B1', status: 0, remark: '' }
const line = (overrides = {}) => ({
  id: 1, editable: true, deleted: false, product: null, quantity: 5, originalQuantity: 5, receivedQty: 0, ...overrides,
})

test('builds the save payload for updates, replacements, new lines and deletions', () => {
  const { payload } = buildEditPayload(order, form, [
    line({ id: 1 }),
    line({ id: 2, quantity: 7 }),
    line({ id: 3, product: { product_id_text: '900' } }),
    line({ id: 4, deleted: true, quantity: 9 }),
    line({ id: null, product: { product_id_text: '901' }, quantity: 2, originalQuantity: 1 }),
  ])
  assert.deepEqual(payload, {
    item_updates: [
      { item_id: 2, expected_order_qty: 5, order_qty: 7 },
      { item_id: 3, expected_order_qty: 5, order_qty: 5, product_id: '900' },
    ],
    new_items: [{ product_id: '901', order_qty: 2 }],
    deleted_items: [{ item_id: 4, expected_order_qty: 5 }],
  })
  assert.equal(payloadChangesItems(payload), true)
})

test('only order fields are sent when nothing in the lines changed', () => {
  const { payload } = buildEditPayload(order, { ...form, remark: '加急' }, [line(), line({ id: 2 })])
  assert.deepEqual(payload, { item_updates: [], new_items: [], remark: '加急' })
  assert.equal(payloadChangesItems(payload), false)
})

test('lines are ignored when the order items are not editable', () => {
  const { payload } = buildEditPayload({ ...order, items_editable: false }, form, [line({ quantity: 8 })])
  assert.deepEqual(payload, { item_updates: [], new_items: [] })
})

test('locked lines never count as changed, even if the quantity was clamped', () => {
  assert.equal(isLineChanged(line({ editable: false, quantity: 3 })), false)
})

test('rejects a new line without product and invalid quantities', () => {
  assert.equal(buildEditPayload(order, form, [line({ id: null, originalQuantity: 1, quantity: 1 })]).error, '请选择新增产品的型号')
  assert.equal(buildEditPayload(order, form, [line({ quantity: 2, receivedQty: 3 })]).error, '请填写有效的下单数量')
})

test('remote product select does not search again on open or clear results while loading', () => {
  // el-select 展开时已用空关键词调用 remote-method；在 visible-change 里再搜、或 load 时清空结果，
  // 会让下拉因「无数据」收起再展开，无限循环请求直至页面崩溃。
  const handlerName = productSelect.match(/@visible-change="(\w+)"/)?.[1]
  assert.ok(handlerName, 'visible-change 必须指向具名函数，便于检查')
  const handler = productSelect.match(new RegExp(`function ${handlerName}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`))?.[0]
  assert.ok(handler, 'visible-change handler should be a named function')
  assert.doesNotMatch(handler, /search\(|\.load\(/, 'visible-change 只允许取消请求，搜索交给 remote-method')
  assert.match(productSelect, /:remote-method="search"/)
  assert.doesNotMatch(productSelect, /\.load\([^)]*clear:\s*true/, '远程搜索不要清空旧结果')
})
