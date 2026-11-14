import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildModel, DECK, kpisAt, layoutAt, tierOf } from '../src/views/domestic_followup/components/stats/churn/shipLayout.js'
import { dayLabel } from '../src/views/domestic_followup/components/stats/churn/churnFormat.js'

const region = (key, extra = {}) => ({ key, owned: 0, stable: 0, critical: 0, warning: 0, public_total: 0, fallen_recent: 0, ...extra })
const customer = (id, remaining, extra = {}) => ({ id, shop_name: `店${id}`, level: 'B级', region: '华东', remaining_days: remaining, clock: 'follow', strap: 'tight', ...extra })

function sample() {
  return {
    regions: [region('华东', { owned: 30, stable: 27, critical: 1, warning: 2, public_total: 9, fallen_recent: 1 }), region('华南', { owned: 5, stable: 5 })],
    customers: [customer(1, 2), customer(2, 9), customer(3, 13), customer(4, 40, { level: 'S级' })],
    fallen: [{ id: 9, shop_name: '落海店', level: 'A级', region: '华东', fallen_days_ago: 3 }],
    kpis: { critical: 1, within_14: 3, fallen_30: 4 },
  }
}

test('tiers follow the agreed day thresholds', () => {
  assert.deepEqual([0, 1, 3, 4, 14, 15].map(tierOf), ['fallen', 'critical', 'critical', 'warning', 'warning', 'stable'])
})

test('stable B/C customers become stacks, S/A stay individual', () => {
  const model = buildModel(sample())
  layoutAt(model, 0)
  const east = model.regions.find(r => r.key === '华东')
  assert.equal(east.stackCount, 26) // 27 稳固 − 1 家单独画的 S 级
  assert.equal(model.items.find(i => i.id === 4).visible, true)
  assert.equal(model.length > 0, true)
})

test('remaining days map to lanes: critical boxes hug the rail, fallen float outside', () => {
  const model = buildModel(sample())
  layoutAt(model, 0)
  const critical = model.items.find(i => i.id === 1), stable = model.items.find(i => i.id === 4), fallen = model.items.find(i => i.id === 9)
  assert.ok(Math.abs(critical.z) > Math.abs(stable.z))
  assert.ok(Math.abs(fallen.z) > DECK.HALF)
  assert.equal(fallen.tier, 'fallen')
})

test('projection and replay move boxes across the rail', () => {
  const model = buildModel(sample())
  assert.deepEqual(kpisAt(model, 0), { critical: 1, within14: 3, fallen: 1 })
  assert.equal(kpisAt(model, 3).fallen, 2) // 第 3 天店 1 落海
  layoutAt(model, -4)
  assert.equal(model.items.find(i => i.id === 9).tier, 'critical') // 4 天前还在甲板上
  layoutAt(model, 14)
  assert.equal(model.items.find(i => i.id === 3).tier, 'fallen')
  assert.equal(model.items.find(i => i.id === 4).tier, 'stable')
})

test('a customer always lands on the same side between refreshes', () => {
  const a = buildModel(sample()), b = buildModel(sample())
  assert.deepEqual(a.items.map(i => i.side), b.items.map(i => i.side))
})

test('day labels use the server Beijing date, not the client clock', () => {
  assert.equal(dayLabel(0, '2026-11-13'), '11 月 13 日')
  assert.equal(dayLabel(18, '2026-11-13'), '12 月 1 日')
  assert.equal(dayLabel(-13, '2026-03-01'), '2 月 16 日')
  assert.equal(dayLabel(1, '2026-12-31'), '1 月 1 日')
})

test('three.js is only reachable through the lazy stage', () => {
  const card = readFileSync(new URL('../src/views/domestic_followup/components/stats/churn/ChurnShipCard.vue', import.meta.url), 'utf8')
  const stage = readFileSync(new URL('../src/views/domestic_followup/components/stats/churn/ChurnShipStage.vue', import.meta.url), 'utf8')
  const vite = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8')
  assert.match(card, /defineAsyncComponent\(\(\) => import\('\.\/ChurnShipStage\.vue'\)\)/)
  assert.doesNotMatch(card, /from 'three'|shipScene/)
  assert.match(stage, /await import\('\.\/shipScene'\)/)
  assert.match(stage, /onDeactivated\(close\)/)
  assert.match(vite, /vendor-three/)
})

test('overdue customers that still have an owner stay on deck as critical today, fall only in projection', () => {
  const data = sample()
  data.customers.push(customer(5, -6))
  data.regions[0].critical += 1
  const model = buildModel(data)
  layoutAt(model, 0)
  const overdue = model.items.find(i => i.id === 5)
  assert.equal(overdue.tier, 'critical')
  assert.ok(Math.abs(overdue.z) < DECK.HALF)
  assert.equal(kpisAt(model, 0).critical, 2)
  layoutAt(model, -3)
  assert.equal(model.items.find(i => i.id === 5).tier, 'critical')
  layoutAt(model, 1)
  assert.equal(model.items.find(i => i.id === 5).tier, 'fallen')
})
