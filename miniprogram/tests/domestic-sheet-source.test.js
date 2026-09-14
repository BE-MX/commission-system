const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const sheetPath = path.resolve(__dirname, '../components/domestic-sheet/domestic-sheet.wxml')
const ordersPath = path.resolve(__dirname, '../pages/domestic/orders/orders.wxml')
const lookupPath = path.resolve(__dirname, '../pages/domestic/lookup/lookup.wxml')
const trackPath = path.resolve(__dirname, '../pages/domestic/track/track.wxml')

function assertDimensionLabels(source, owner) {
  for (const field of [
    'order_category_label',
    'order_type_label',
    'order_channel_label',
  ]) {
    assert.match(source, new RegExp(`\\{\\{${owner}\\.${field}\\}\\}`))
  }
}

test('special badge uses the stable order category code', function () {
  const source = fs.readFileSync(sheetPath, 'utf8')

  assert.match(source, /wx:if="\{\{item\.order_category === 'special'\}\}"/)
  assert.doesNotMatch(
    source,
    /order_type_label\s*===\s*['"]特单['"]/
  )
})

test('domestic order list and detail show all three order dimensions', function () {
  const source = fs.readFileSync(ordersPath, 'utf8')

  assertDimensionLabels(source, 'item')
  assertDimensionLabels(source, 'detail')
})

test('lookup page shows all three order dimensions', function () {
  assertDimensionLabels(fs.readFileSync(lookupPath, 'utf8'), 'order')
})

test('tracking page shows only the customer-facing whitelist', function () {
  // 进度码免登录页 2026-09-14 起只留店面/客户单号/顾客和产品工艺参数，
  // 订单维度、状态、工序进度一律不展示（服务端也不下发）
  const source = fs.readFileSync(trackPath, 'utf8')

  assert.match(source, /\{\{order\.customer_name\}\}/)
  assert.match(source, /\{\{order\.order_no\}\}/)
  assert.match(source, /\{\{order\.guest_name\}\}/)
  for (const field of [
    'order_category_label',
    'order_type_label',
    'order_channel_label',
    'status_label',
    'current_process',
    'stepView',
  ]) {
    assert.doesNotMatch(source, new RegExp(field))
  }
})

test('domestic reporting sheet shows all three order dimensions', function () {
  assertDimensionLabels(fs.readFileSync(sheetPath, 'utf8'), 'item')
})
