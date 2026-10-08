import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { defaultQuery, cleanQuery, applySavedView, validateQuery, latestRequestGate, groupedInsights, actionCompletionError, comparisonText } from '../src/views/domestic_decision/state.js'
import { currentBeijingDate } from '../src/utils/datetime.js'

const options = { dimensions: { craft: [], length: [], color: [], province: [] }, permissions: { all: false, finance: false } }
test('business month default follows Beijing midnight even on a non-Beijing client', () => {
  const today = currentBeijingDate(new Date('2026-09-30T16:01:00Z'))
  assert.equal(today, '2026-10-01')
  assert.deepEqual([defaultQuery(today).start_date, defaultQuery(today).end_date], ['2026-10-01', '2026-10-01'])
})
test('permission reduction strips finance fields, all scope and owner constraints', () => {
  const body = cleanQuery({ ...defaultQuery('2026-10-08'), scope: 'all', owner_ids: [99], dimensions: ['settle_mode', 'craft'], filters: { membership_level: ['gold'], settle_mode: ['credit'], color: ['红'], unknown: ['a'] }, finance_related_customers: true }, options)
  assert.equal(body.scope, 'mine'); assert.equal(body.finance_related_customers, false)
  assert.deepEqual(body.owner_ids, []); assert.deepEqual(body.dimensions, ['craft']); assert.deepEqual(body.filters, { color: ['红'] })
})
test('rolling view preserves inclusive duration across year and leap boundaries', () => {
  const view = { time_mode: 'rolling', query: { ...defaultQuery('2024-03-01'), start_date: '2024-02-28', end_date: '2024-03-01' } }
  const body = applySavedView(view, '2026-01-01', options)
  assert.equal(body.start_date, '2025-12-30'); assert.equal(body.end_date, '2026-01-01')
  assert.equal(view.query.start_date, '2024-02-28')
})
test('fixed views remain fixed and shared queries cannot grant receiver finance access', () => {
  const view = { time_mode: 'fixed', query: { ...defaultQuery('2026-09-08'), scope: 'all', finance_related_customers: true } }
  const body = applySavedView(view, '2026-10-08', options)
  assert.equal(body.end_date, '2026-09-08'); assert.equal(body.scope, 'mine'); assert.equal(body.finance_related_customers, false)
})
test('query validation rejects reverse, excessive and duplicate dimension requests', () => {
  const query = defaultQuery('2026-10-08')
  assert.equal(validateQuery(query), '')
  assert.ok(validateQuery({ ...query, start_date: '2026-10-09' }))
  assert.ok(validateQuery({ ...query, start_date: '2020-01-01' }))
  assert.ok(validateQuery({ ...query, dimensions: ['craft', 'craft'] }))
})
test('late analysis and profile results cannot replace the newest selection or closed drawer', () => {
  const gate = latestRequestGate(), first = gate.next(), second = gate.next()
  assert.equal(gate.isCurrent(first), false); assert.equal(gate.isCurrent(second), true)
  gate.invalidate(); assert.equal(gate.isCurrent(second), false)
})
test('customer insights group reasons without merging different customers or group rules', () => {
  const rows = [...Array.from({ length: 5 }, (_, index) => ({ customer_id: 1, rule_key: `r${index}` })), { customer_id: 2, rule_key: 'r0' }, { rule_key: 'quality' }]
  const groups = groupedInsights(rows)
  assert.equal(groups.length, 3); assert.equal(groups[0].reasons.length, 3); assert.equal(groups[1].customer_id, 2); assert.equal(groups[2].customer_id, undefined)
})
test('completed actions require actual result and registered type; note alone does not complete', () => {
  assert.ok(actionCompletionError({ status: 'done', result: ' ', result_type: 'other' }))
  assert.ok(actionCompletionError({ status: 'done', result: '已联系' }))
  assert.equal(actionCompletionError({ status: 'done', result: '客户暂无采购计划', result_type: 'contacted' }), '')
  assert.equal(actionCompletionError({ status: 'in_progress', result: '' }), '')
})
test('zero and unknown baselines are distinct from genuine 0% change', () => {
  assert.match(comparisonText({ previous: 0, rate: null }), /对照为零/)
  assert.match(comparisonText({ previous: null, rate: null }), /未知/)
  assert.match(comparisonText({ previous: 100, rate: 0 }), /\+0%/)
})
test('production page only uses authenticated domain client and shipped ECharts imports', () => {
  const api = readFileSync(new URL('../src/api/domesticDecision.js', import.meta.url), 'utf8')
  const chart = readFileSync(new URL('../src/views/domestic_decision/components/DecisionChart.vue', import.meta.url), 'utf8')
  assert.match(api, /domesticDecisionClient/); assert.match(chart, /echarts\/core/)
  assert.doesNotMatch(api + chart, /https?:\/\/|data\.js|axios\.create/)
})
