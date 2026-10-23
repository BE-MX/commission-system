import test from 'node:test'
import assert from 'node:assert/strict'
import {
  SEASON_WEIGHTS, splitWeighted, allocInt, splitYearToQuarters, splitQuarterToMonths,
  validateChildSum, goalKey, indexGoalRows, goalRowsFromEdits, round2,
} from '../src/views/perf-goal/helpers.js'

test('季节系数为 20/25/25/30', () => {
  assert.deepEqual(SEASON_WEIGHTS, [0.2, 0.25, 0.25, 0.3])
})

test('金额按权重拆分：末位调差保证合计精确', () => {
  assert.deepEqual(splitWeighted(3100000, SEASON_WEIGHTS), [620000, 775000, 775000, 930000])
  // 不可整除时末位吸收误差
  const parts = splitWeighted(1000000.01, SEASON_WEIGHTS)
  assert.equal(round2(parts.reduce((a, b) => a + b, 0)), 1000000.01)
  assert.deepEqual(splitWeighted(100, [1, 1, 1]), [33.33, 33.33, 33.34])
  assert.deepEqual(splitWeighted(0, SEASON_WEIGHTS), [0, 0, 0, 0])
})

test('整数按权重拆分：最大余数法保证合计精确', () => {
  assert.deepEqual(allocInt(25, SEASON_WEIGHTS), [5, 6, 6, 8])
  assert.deepEqual(allocInt(998, SEASON_WEIGHTS), [200, 250, 249, 299])
  assert.deepEqual(allocInt(74, [1, 1, 1]), [25, 25, 24])
  const odd = allocInt(10, [1, 1, 1, 1])
  assert.equal(odd.reduce((a, b) => a + b, 0), 10)
  odd.forEach(v => assert.equal(Number.isInteger(v), true))
})

test('年→季 / 季→月 拆分按指标类型选择整数或金额口径', () => {
  assert.deepEqual(splitYearToQuarters(3100000), [620000, 775000, 775000, 930000])
  assert.deepEqual(splitYearToQuarters(25, { integer: true }), [5, 6, 6, 8])
  assert.deepEqual(splitQuarterToMonths(900000), [300000, 300000, 300000])
  assert.deepEqual(splitQuarterToMonths(1000000.07), [333333.36, 333333.36, 333333.35])
  assert.deepEqual(splitQuarterToMonths(6, { integer: true }), [2, 2, 2])
  // 全链路：年度 → 季度 → 月度合计仍等于年度
  const q = splitYearToQuarters(876543.21)
  const m = q.flatMap(v => splitQuarterToMonths(v))
  assert.equal(round2(m.reduce((a, b) => a + b, 0)), 876543.21)
  const qi = splitYearToQuarters(53, { integer: true })
  const mi = qi.flatMap(v => splitQuarterToMonths(v, { integer: true }))
  assert.equal(mi.reduce((a, b) => a + b, 0), 53)
})

test('目标校验：同级子项之和 ≠ 父项时返回差异，容忍 0.005 以内浮点误差', () => {
  assert.deepEqual(validateChildSum(3100000, [620000, 775000, 775000, 930000]), null)
  assert.deepEqual(validateChildSum(3100000, [620000, 775000, 775000, 935000]), { sum: 3105000, diff: 5000 })
  assert.deepEqual(validateChildSum(52, [13, 13, 13, 15]), { sum: 54, diff: 2 })
  assert.deepEqual(validateChildSum(900000, [300000, 300000, 292000]), { sum: 892000, diff: -8000 })
  // 浮点噪音不报警
  assert.equal(validateChildSum(0.3, [0.1, 0.1, 0.1]), null)
  // 父项为 0、子项全 0 通过
  assert.equal(validateChildSum(0, [0, 0, 0, 0]), null)
})

test('目标行索引与编辑暂存双向转换', () => {
  const key = goalKey('u1', 'gmv', 'quarter', 2, null)
  assert.equal(key, 'u1|gmv|quarter|2|')
  const rows = [
    { user_id: 'u1', metric: 'gmv', granularity: 'year', quarter: null, month: null, target_value: 100 },
    { user_id: 'u1', metric: 'gmv', granularity: 'quarter', quarter: 2, month: null, target_value: 25 },
  ]
  const map = indexGoalRows(rows)
  assert.equal(map.get(goalKey('u1', 'gmv', 'year', null, null)), 100)
  assert.equal(map.get(key), 25)
  const edits = { [key]: 30, 'u2|new_sign|year||': 40 }
  assert.deepEqual(goalRowsFromEdits(edits), [
    { user_id: 'u1', metric: 'gmv', granularity: 'quarter', quarter: 2, month: null, target_value: 30 },
    { user_id: 'u2', metric: 'new_sign', granularity: 'year', quarter: null, month: null, target_value: 40 },
  ])
  // 非法输入按 0 保存（编辑框已拦截负数/非数字）
  assert.equal(goalRowsFromEdits({ 'u1|gmv|year||': '' })[0].target_value, 0)
})
