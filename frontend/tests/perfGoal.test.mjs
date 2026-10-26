import test from 'node:test'
import assert from 'node:assert/strict'
import {
  METRICS, MKEYS, fmtUsd, fmtInt, fmtMetric, fmtPp, fmtRate,
  rateOf, deltaPp, round2, statusOf, normalizeStatus, sortRanking, sumMetricCells,
} from '../src/views/perf-goal/helpers.js'

test('四指标契约 key 与后端一致', () => {
  assert.deepEqual(MKEYS, ['gmv', 'new_sign', 'repeat_customers', 'repeat_amount'])
  assert.equal(METRICS.find(m => m.key === 'gmv').money, true)
  assert.equal(METRICS.find(m => m.key === 'new_sign').money, false)
})

test('格式化：千分位 / USD / pp / 百分率', () => {
  assert.equal(fmtUsd(1234567), '$1,234,567')
  assert.equal(fmtUsd(1234.5, { cents: true }), '$1,234.50')
  assert.equal(fmtUsd(null), '—')
  assert.equal(fmtInt(1234567), '1,234,567')
  assert.equal(fmtMetric('new_sign', 744, { withUnit: true }), '744 个')
  assert.equal(fmtMetric('repeat_amount', 4954131.79), '$4,954,132')
  assert.equal(fmtPp(0.94), '+0.9pp')
  assert.equal(fmtPp(-12.94), '-12.9pp')
  assert.equal(fmtRate(79.24), '79.2%')
  assert.equal(fmtRate(null), '—')
})

test('完成率与 delta_pp 计算', () => {
  assert.equal(rateOf(12426389.58, 15697000), 79.2)
  assert.equal(rateOf(100, 0), null)
  assert.equal(deltaPp(79.2, 80.1), -0.9)
  assert.equal(deltaPp(108.5, 80.1), 28.4)
  assert.equal(deltaPp(null, 80.1), null)
  assert.equal(round2(0.1 + 0.2), 0.3)
})

test('status 判定：completed/on_track/lagging/critical/no_target', () => {
  assert.equal(statusOf(null, 80.1).key, 'no_target')
  assert.equal(statusOf(100, 80.1).key, 'completed')
  assert.equal(statusOf(141.4, 80.1).key, 'completed')
  assert.equal(statusOf(80.1, 80.1).key, 'on_track')
  assert.equal(statusOf(90, 80.1).key, 'on_track')
  assert.equal(statusOf(79.2, 80.1).key, 'lagging')
  assert.equal(statusOf(50.2, 80.1).key, 'lagging')
  assert.equal(statusOf(50.0, 80.1).key, 'critical')
  assert.equal(statusOf(30.5, 80.1).key, 'critical')
  // 非年度周期时间进度按 100 处理
  assert.equal(statusOf(100, 100).key, 'completed')
  assert.equal(statusOf(80, 100).key, 'lagging')
  // 状态色映射
  assert.equal(statusOf(null).tag, 'gray')
  assert.equal(normalizeStatus('critical').tag, 'darkred')
  assert.equal(normalizeStatus('unknown').key, 'no_target')
})

test('排名排序：默认 GMV 完成率降序，支持切换键与方向，平局按 user_id 稳定', () => {
  const rows = [
    { user_id: 'u1', gmv: { target: 100, achieved: 90, rate: 90 }, delta_pp: 9.9 },
    { user_id: 'u2', gmv: { target: 200, achieved: 300, rate: 150 }, delta_pp: 69.9 },
    { user_id: 'u3', gmv: { target: 100, achieved: 50, rate: 50 }, delta_pp: -30.1 },
    { user_id: 'u4', gmv: { target: 100, achieved: 50, rate: 50 }, delta_pp: -30.1 },
  ]
  assert.deepEqual(sortRanking(rows).map(r => r.user_id), ['u2', 'u1', 'u3', 'u4'])
  assert.deepEqual(sortRanking(rows, 'gmv_rate', 'asc').map(r => r.user_id), ['u3', 'u4', 'u1', 'u2'])
  assert.deepEqual(sortRanking(rows, 'gmv_achieved').map(r => r.user_id)[0], 'u2')
  assert.deepEqual(sortRanking(rows, 'delta_pp').map(r => r.user_id)[0], 'u2')
  assert.deepEqual(sortRanking(rows, 'gmv_target').map(r => r.user_id)[0], 'u2')
  // 不改原数组
  assert.equal(rows[0].user_id, 'u1')
})

test('主名单合计：四指标 target/achieved 逐格求和且 rate 由合计重算（与排名表口径一致）', () => {
  const rows = [
    { gmv: { target: 3100000, achieved: 2110225.67 }, new_sign: { target: 25, achieved: 24 }, repeat_customers: { target: 15, achieved: 10 }, repeat_amount: { target: 1302000, achieved: 900000.5 } },
    { gmv: { target: 730000, achieved: 769294.07 }, new_sign: { target: 39, achieved: 76 }, repeat_customers: { target: 23, achieved: 30 }, repeat_amount: { target: 306600, achieved: 332771.29 } },
    { gmv: { target: 0, achieved: 44100.82 }, new_sign: { target: 0, achieved: 41 }, repeat_customers: { target: 0, achieved: 5 }, repeat_amount: { target: 0, achieved: 20000 } },
  ]
  const total = sumMetricCells(rows)
  assert.equal(total.gmv.target, 3830000)
  assert.equal(total.gmv.achieved, round2(2110225.67 + 769294.07 + 44100.82))
  assert.equal(total.gmv.rate, rateOf(total.gmv.achieved, total.gmv.target))
  assert.equal(total.new_sign.achieved, 141)
  assert.equal(total.repeat_customers.achieved, 45)
  assert.equal(total.repeat_amount.achieved, round2(900000.5 + 332771.29 + 20000))
  // 空目标合计不产生 NaN 率
  const empty = sumMetricCells([])
  assert.equal(empty.gmv.rate, null)
  // 缺格行被跳过
  const partial = sumMetricCells([{ gmv: { target: 100, achieved: 50 } }])
  assert.equal(partial.new_sign.achieved, 0)
})
