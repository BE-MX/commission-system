import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildMonthSummary,
  groupedRows,
  monthOf,
  roleCommission,
  roleField,
  visibleDetailCount,
} from '../src/views/commission/commissionGrouping.js'

test('monthOf 取回款日期前 7 位，空值归入未设置日期', () => {
  assert.equal(monthOf('2026-09-18'), '2026-09')
  assert.equal(monthOf('2026-09-01 12:30:00'), '2026-09')
  assert.equal(monthOf(''), '未设置日期')
  assert.equal(monthOf(null), '未设置日期')
})

test('roleField/roleCommission 按角色取提成字段', () => {
  assert.equal(roleField('salesperson', 'commission'), 'salesperson_commission')
  assert.equal(roleField('supervisor', 'rate'), 'supervisor_rate')
  assert.equal(roleField('second_supervisor', 'commission'), 'second_supervisor_commission')
  const row = { salesperson_commission: '12.50', supervisor_commission: 0 }
  assert.equal(roleCommission(row, 'salesperson'), 12.5)
  assert.equal(roleCommission(row, 'supervisor'), 0)
  assert.equal(roleCommission(row, 'second_supervisor'), 0)
})

test('visibleDetailCount 只计提成非 0 的行', () => {
  const rows = [
    { supervisor_commission: 3 },
    { supervisor_commission: 0 },
    { supervisor_commission: -1 },
  ]
  assert.equal(visibleDetailCount(rows, 'supervisor'), 2)
  assert.equal(visibleDetailCount([], 'supervisor'), 0)
  assert.equal(visibleDetailCount(null, 'supervisor'), 0)
})

test('groupedRows 过滤零提成行、按月升序分组并合计', () => {
  const rows = [
    { id: 3, collection_date: '2026-09-10', payment_amount: 100, service_fee: 2, salesperson_commission: 10 },
    { id: 1, collection_date: '2026-08-02', payment_amount: 50, service_fee: 1, salesperson_commission: 5 },
    { id: 2, collection_date: '2026-08-01', payment_amount: 70, service_fee: 3, salesperson_commission: 7 },
    { id: 4, collection_date: '2026-08-05', payment_amount: 999, service_fee: 9, salesperson_commission: 0 },
  ]
  const groups = groupedRows(rows, 'salesperson')
  assert.deepEqual(groups.map(g => g.month), ['2026-08', '2026-09'])
  const august = groups[0]
  assert.equal(august.isMonthGroup, true)
  assert.equal(august.id, 'month-2026-08')
  assert.equal(august.children.length, 2)
  assert.deepEqual(august.children.map(r => r.id), [2, 1])
  assert.equal(august.total_payment_amount, 120)
  assert.equal(august.total_service_fee, 4)
  assert.equal(august.total_commission, 12)
})

test('buildMonthSummary 三种角色分别合计，回款按行 ID 去重', () => {
  const detail = {
    salesperson_details: [
      { id: 1, collection_date: '2026-09-02', payment_amount: 100, salesperson_commission: 10 },
      { id: 2, collection_date: '2026-08-02', payment_amount: 50, salesperson_commission: 5 },
    ],
    supervisor_details: [
      { id: 1, collection_date: '2026-09-02', payment_amount: 100, supervisor_commission: 3 },
    ],
    second_supervisor_details: [],
  }
  const summary = buildMonthSummary(detail, '2026-09')
  assert.equal(summary.total_payment_amount, 100)
  assert.equal(summary.total_salesperson_commission, 10)
  assert.equal(summary.total_supervisor_commission, 3)
  assert.equal(summary.total_second_supervisor_commission, 0)
  assert.equal(summary.total_commission, 13)
})

test('buildMonthSummary 对空明细与缺失字段安全', () => {
  const summary = buildMonthSummary({}, '2026-09')
  assert.equal(summary.total_payment_amount, 0)
  assert.equal(summary.total_commission, 0)
  const empty = buildMonthSummary(null, '2026-09')
  assert.equal(empty.total_commission, 0)
})

test('groupedRows 同日期按行 ID 决胜，未设置日期排在月份之后', () => {
  const rows = [
    { id: 9, collection_date: '2026-09-10', salesperson_commission: 1 },
    { id: 3, collection_date: '2026-09-10', salesperson_commission: 1 },
    { id: 5, collection_date: '', salesperson_commission: 1 },
  ]
  const groups = groupedRows(rows, 'salesperson')
  assert.deepEqual(groups.map(g => g.month), ['2026-09', '未设置日期'])
  assert.deepEqual(groups[0].children.map(r => r.id), [3, 9])
})
