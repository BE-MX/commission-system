import test from 'node:test'
import assert from 'node:assert/strict'
import { statusBadgeColumns, columnIssues, withDictionary, statusFunctionDictionary } from './helpers/statusBadgeColumns.mjs'
import { TRACKING_STATUS } from '../src/views/tracking/trackingStatus.js'

const columns = template => statusBadgeColumns(`<template>${template}</template>`)
test('short and long Chinese statuses include cell and pill padding', () => {
  const [narrow] = columns('<el-table-column min-width="84"><StatusBadge>已同步</StatusBadge></el-table-column>')
  assert.equal(narrow.requiredWidth, 110)
  assert.equal(columnIssues(narrow).length, 1)
  const [long] = columns('<el-table-column min-width="160"><StatusBadge>同步结果待核对</StatusBadge></el-table-column>')
  assert.equal(long.requiredWidth, 160)
  assert.deepEqual(columnIssues(long), [])
})
test('multiple pills share a column without summing their widths', () => {
  const [row] = columns('<el-table-column min-width="100"><StatusBadge>启用</StatusBadge><StatusBadge>主推</StatusBadge></el-table-column>')
  assert.deepEqual(columnIssues(row), [])
})
test('displayed ternary labels count, machine codes in tests do not', () => {
  const [row] = columns(`<el-table-column min-width="110"><StatusBadge>{{ row.status === 'very_long_machine_state' ? '待审核' : '已审核' }}</StatusBadge></el-table-column>`)
  assert.equal(row.requiredWidth, 110)
  assert.deepEqual(columnIssues(row), [])
})
test('an expand control is excluded while its nested badge column is checked', () => {
  const rows = columns('<el-table-column type="expand" width="48"><el-table><el-table-column min-width="80"><StatusBadge>已完成</StatusBadge></el-table-column></el-table></el-table-column>')
  assert.deepEqual(columnIssues(rows[0]), [])
  assert.equal(columnIssues(rows[1]).length, 1)
})
test('fixed widths and contradictory maximum widths cannot hide narrow badges', () => {
  const [row] = columns('<el-table-column width="80" min-width="160" max-width="60"><StatusBadge>已完成</StatusBadge></el-table-column>')
  assert.equal(columnIssues(row).length, 2)
})

test('dynamic dictionary labels catch the four-character customs status', () => {
  const [row] = columns('<el-table-column min-width="110"><StatusBadge>{{ statusText(row.status) }}</StatusBadge></el-table-column>')
  const checked = withDictionary(row, TRACKING_STATUS)
  assert.equal(checked.requiredWidth, 120)
  assert.equal(columnIssues(checked).length, 1)
  assert.deepEqual(columnIssues({ ...checked, width: 120 }), [])
})

test('local display maps are read without evaluating setup or unrelated labels', () => {
  const source = `<script setup>throw new Error('must not execute'); const unrelated = { x: '很长的无关字符串' }; const riskLabel = value => ({ due: '到期提醒' }[value] || value); function credibilityLabel(value) { const map = { unverifiable: '无法核实' }; return map[value] || value }</script>`
  assert.deepEqual(statusFunctionDictionary(source, 'riskLabel'), { due: '到期提醒' })
  assert.deepEqual(statusFunctionDictionary(source, 'credibilityLabel'), { unverifiable: '无法核实' })
  assert.throws(() => statusFunctionDictionary(source, 'missing'), /not found/)
})
