const test = require('node:test')
const assert = require('node:assert/strict')

const routing = require('../utils/domestic-routing')

const options = [
  { code: 'dandong', label: '丹东' },
  { code: 'lixiaohong', label: '李晓宏' }
]

test('quantity decision emits ordered positive outcomes and derived qty', function () {
  assert.deepEqual(
    routing.buildDecisionSubmission(options, { lixiaohong: '8', dandong: '12' }, 20, 'quantity'),
    { qty: 20, outcomes: { dandong: 12, lixiaohong: 8 } }
  )
})

test('quantity decision preserves every configured option including zero', function () {
  assert.deepEqual(
    routing.buildDecisionSubmission(options, { dandong: '20', lixiaohong: '0' }, 20, 'quantity'),
    { qty: 20, outcomes: { dandong: 20, lixiaohong: 0 } }
  )
})

test('quantity decision rejects empty, negative, fractional, and oversized allocations', function () {
  assert.throws(function () { routing.buildDecisionSubmission(options, {}, 20, 'quantity') })
  assert.throws(function () { routing.buildDecisionSubmission(options, { dandong: -1 }, 20, 'quantity') })
  assert.throws(function () { routing.buildDecisionSubmission(options, { dandong: 1.5 }, 20, 'quantity') })
  assert.throws(function () { routing.buildDecisionSubmission(options, { dandong: 21 }, 20, 'quantity') })
})

test('unit decision requires exactly one known option', function () {
  assert.deepEqual(
    routing.buildDecisionSubmission(options, { lixiaohong: true }, 1, 'unit'),
    { qty: 1, outcomes: { lixiaohong: 1 } }
  )
  assert.throws(function () {
    routing.buildDecisionSubmission(options, { dandong: true, lixiaohong: true }, 1, 'unit')
  })
  assert.throws(function () { routing.buildDecisionSubmission(options, { other: true }, 1, 'unit') })
})

test('progress uses passed quantity while keeping actual and skipped separate', function () {
  assert.deepEqual(
    routing.decorateProgress({ completed_qty: 12, skipped_qty: 8, passed_qty: 20, order_qty: 20 }),
    { completedQty: 12, skippedQty: 8, passedQty: 20, percent: 100, done: true }
  )
})

test('public progress labels skipped work without exposing audit fields', function () {
  assert.deepEqual(
    routing.publicStep({
      completed_qty: 0,
      skipped_qty: 4,
      passed_qty: 4,
      order_qty: 4,
      reportable_qty: 0,
      step_order: 13,
      process_name: '毛坯维修',
      last_reported_by: '内部员工',
      skip_reason: '内部原因'
    }),
    {
      completed_qty: 0,
      skipped_qty: 4,
      passed_qty: 4,
      order_qty: 4,
      reportable_qty: 0,
      step_order: 13,
      process_name: '毛坯维修',
      skip_label: '无需此工序'
    }
  )
})
