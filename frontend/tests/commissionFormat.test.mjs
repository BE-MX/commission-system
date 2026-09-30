import test from 'node:test'
import assert from 'node:assert/strict'
import {
  batchStatusLabel,
  batchStatusType,
  cny,
  commissionRate,
  confirmPercent,
  confirmationStatusLabel,
  confirmationStatusType,
  exchangeRate,
  periodLabel,
  roleLabel,
  usd,
  usdOrDash,
} from '../src/views/commission/commissionFormat.js'

test('usd/cny 千分位且保留两位小数', () => {
  assert.equal(usd(1234.5), '$1,234.50')
  assert.equal(usd(0), '$0.00')
  assert.equal(usd(null), '$0.00')
  assert.equal(usd(undefined), '$0.00')
  assert.equal(usd('2560'), '$2,560.00')
  assert.equal(usd(-25.5), '$-25.50')
  assert.equal(cny(987654.3), '¥987,654.30')
})

test('usdOrDash 区分未计算与真 0', () => {
  assert.equal(usdOrDash(null), '-')
  assert.equal(usdOrDash(undefined), '-')
  assert.equal(usdOrDash(''), '-')
  assert.equal(usdOrDash(0), '$0.00')
  assert.equal(usdOrDash(1234.5), '$1,234.50')
})

test('汇率固定 6 位小数；提成比例统一 2 位小数，未配置显示 -', () => {
  assert.equal(exchangeRate(7.12345), '7.123450')
  assert.equal(exchangeRate(0), '0.000000')
  assert.equal(commissionRate(0.0525), '5.25%')
  assert.equal(commissionRate(0.05), '5.00%')
  assert.equal(commissionRate(null), '-')
  assert.equal(commissionRate(undefined), '-')
  assert.equal(commissionRate(''), '-')
  assert.equal(commissionRate(0), '0.00%')
  assert.equal(commissionRate(0.1), '10.00%')
})

test('批次状态映射完整，未知状态原样展示且 tag 为 info', () => {
  assert.equal(batchStatusType('draft'), 'info')
  assert.equal(batchStatusType('calculated'), 'info')
  assert.equal(batchStatusType('confirming'), 'warning')
  assert.equal(batchStatusType('confirmed'), 'success')
  assert.equal(batchStatusType('voided'), 'danger')
  assert.equal(batchStatusType('mystery'), 'info')
  assert.equal(batchStatusLabel('confirmed'), '已确认')
  assert.equal(batchStatusLabel('mystery'), 'mystery')
})

test('确认状态映射与进度百分比口径', () => {
  assert.equal(confirmationStatusType('partial_confirmed'), 'warning')
  assert.equal(confirmationStatusType('all_confirmed'), 'success')
  assert.equal(confirmationStatusLabel('not_started'), '未开始')
  assert.equal(confirmationStatusLabel('not_required'), '无需确认')
  assert.equal(confirmPercent({ confirmed_count: 1, expected_confirm_count: 3 }), 33)
  assert.equal(confirmPercent({ confirmed_count: 5, expected_confirm_count: 3 }), 100)
  assert.equal(confirmPercent({ confirmed_count: 2, expected_confirm_count: 0 }), 0)
  assert.equal(confirmPercent(null), 0)
})

test('周期类型与角色中文名', () => {
  assert.equal(periodLabel('monthly'), '月度')
  assert.equal(periodLabel('quarterly'), '季度')
  assert.equal(periodLabel('semi_annual'), '半年')
  assert.equal(periodLabel('annual'), '年度')
  assert.equal(roleLabel('salesperson'), '业务员')
  assert.equal(roleLabel('supervisor'), '一级主管')
  assert.equal(roleLabel('second_supervisor'), '二级主管')
  assert.equal(roleLabel('other'), 'other')
})
