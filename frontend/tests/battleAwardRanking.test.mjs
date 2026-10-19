import test from 'node:test'
import assert from 'node:assert/strict'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'
import { formatMoney } from '../src/utils/money.js'

const overview = loadComponent('../../src/views/battle-report/components/AwardOverview.vue', {
  '@/utils/money': { formatMoney },
})
const components = Object.fromEntries(['el-alert', 'el-empty', 'el-progress', 'StatusBadge'].map(name => [name, slotShell]))
function person(id, progress, qualified, score) {
  return { member_id: id, user_name: `Person${id}`, overall_rank: id, rank: qualified ? 1 : null,
    score, qualified, gmv_complete: true, progress_percent: progress, gmv: String(progress), target: '100',
    baseline: '100', top_five: false, new_count: 1, repeat_count: 0, repeat_orders: 0, repeat_amount: '0' }
}
function render(t, people, extra = {}) {
  return mountComponent(t, overview, { data: { award_kind: 'annual_repurchase', data_complete: true,
    issues: [], people, qualified: people.filter(p => p.qualified), unqualified: people.filter(p => !p.qualified), ...extra } }, undefined, components)
}

test('one total board keeps score order across targets and uses total rank rather than eligible rank', t => {
  const ui = render(t, [person(1, 80, false, '10'), person(2, 120, true, '5')])
  assert.equal(ui.find(n => n.type === 'article').length, 2)
  assert.ok(ui.text().indexOf('Person1') < ui.text().indexOf('Person2'))
  assert.match(ui.text(), /总榜第1名/)
  assert.match(ui.text(), /总榜第2名/)
  assert.doesNotMatch(ui.text(), /候选第1名|未达GMV门槛 · 冲刺进度/)
})

test('only known progress below the exact target turns red; 100 percent and unknown progress do not', t => {
  const unknown = { ...person(4, null, false, '1'), gmv_complete: false }
  const ui = render(t, [person(1, 99.999, false, '4'), person(2, 100, true, '3'), person(3, 150, true, '2'), unknown])
  const bars = ui.find(n => n.props && 'percentage' in n.props)
  assert.deepEqual(bars.map(n => n.props.status), ['exception', 'success', 'success', undefined])
  assert.deepEqual(bars.map(n => n.props.percentage), [99.999, 100, 100, 0])
  assert.match(ui.text(), /99\.9%/)
})

test('incomplete data retains the existing pending ranking protection', t => {
  const ui = render(t, [{ ...person(1, 80, false, '10'), overall_rank: null }], { data_complete: false })
  assert.match(ui.text(), /排名待核对/)
  assert.doesNotMatch(ui.text(), /总榜第1名/)
})

test('annual amount includes new-only customers while repeat counts stay zero', t => {
  const ui = render(t, [{ ...person(1, 80, false, '1'), repeat_amount: '125.12' }])
  assert.match(ui.text(), /新签复购金额＝2026年新签客户的新签订单金额＋后续复购订单金额/)
  assert.match(ui.text(), /含尚未复购的客户/)
  assert.match(ui.text(), /复购 0 客户 \/ 0 笔 · 新签复购金额 \$125\.12/)
})
