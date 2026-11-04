import assert from 'node:assert/strict'
import { test } from 'node:test'
import { latestRequestGate, safeDestination, normalizeDetail, analysisLabel, REASON_FILTERS } from '../src/views/client_desk/deskController.js'

test('late customer / evidence responses lose authority after customer or filter changes', () => {
  const gate = latestRequestGate()
  const a = gate.next(), b = gate.next()
  assert.equal(gate.current(a), false)
  assert.equal(gate.current(b), true)
  gate.invalidate()
  assert.equal(gate.current(b), false)
})
test('report and WA navigation only accepts scoped local destinations or HTTPS wa.me', () => {
  assert.equal(safeDestination('/client-desk?company_id=9007199254740993'), '/client-desk?company_id=9007199254740993')
  assert.equal(safeDestination('https://wa.me/15555555555?text=Hi%20there'), 'https://wa.me/15555555555?text=Hi%20there')
  for (const url of ['//evil.example', 'javascript:alert(1)', 'https://wa.me.evil.example', 'http://wa.me/1', '/login', null]) assert.equal(safeDestination(url), null)
})
test('backend draft field is preserved verbatim, unknown monetary values remain unknown', () => {
  const data = normalizeDetail({ card: { company_id: '9007199254740993' }, suggestion: { draft_message: 'Check [stock]\n你好' }, orders_summary: { amount_usd: null } })
  assert.equal(data.card.company_id, '9007199254740993')
  assert.equal(data.suggestion.draft, 'Check [stock]\n你好')
  assert.equal(data.orders_summary.amount_usd, null)
})
test('uncertain analysis and source rules remain distinct from model success', () => {
  assert.match(analysisLabel('ambiguous'), /未确认/)
  assert.match(analysisLabel('rule_only'), /规则/)
  assert.deepEqual(REASON_FILTERS.map(x => x.value), ['R1_UNREPLIED','R7_AWAITING_CUSTOMER','R2_FOLLOWUP_DUE','R8_NEW_LEAD'])
})
