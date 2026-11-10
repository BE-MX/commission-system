import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { test } from 'node:test'
import { requestKey, latestRequestGate, safeDestination, normalizeDetail, analysisLabel, REASON_FILTERS, revalidatedDraft, copyOrFallback, timelineType, timelineTitle, timelineSummary, orderAmount } from '../src/views/client_desk/deskController.js'

test('private-sea writes get distinct request IDs on LAN HTTP without randomUUID', (t) => {
  t.mock.getter(globalThis, 'crypto', () => ({
    getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
  }))
  const first = requestKey()
  const second = requestKey()
  const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
  assert.match(first, uuidV4)
  assert.match(second, uuidV4)
  assert.notEqual(first, second)
})

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

test('timeline uses readable source names and preserves zero versus an unknown order amount', () => {
  const order = { source: 'order', title: 'October order', order_name: 'October order', order_no: '24366', status_name: '已结束' }
  assert.equal(timelineTitle(order), 'October order')
  assert.equal(timelineSummary(order), '单号 24366 · 已结束')
  assert.equal(timelineTitle({ source: 'rule' }), '系统提醒')
  assert.equal(timelineType({ source: 'rule', card: { name: 'Customer' } }), '客户档案')
  assert.equal(timelineTitle({ source: 'followup', channel: 'phone' }), '电话')
  assert.match(orderAmount(0), /USD\s+0\.00/)
  assert.match(orderAmount(241.92), /USD\s+241\.92/)
  assert.equal(orderAmount(null), '暂无同步金额')
})

test('copy revalidates the exact current suggestion and refuses revoked or changed sources', async () => {
  let reads = 0
  const read = async id => { reads++; assert.equal(id, '101'); return { suggestion: { id: '7', draft_message: 'Fresh authorized draft' } } }
  assert.equal((await revalidatedDraft(read, '101', '7', () => true)).suggestion.draft, 'Fresh authorized draft')
  assert.equal(reads, 1)
  await assert.rejects(revalidatedDraft(async () => ({ suggestion: null }), '101', '7', () => true))
  await assert.rejects(revalidatedDraft(read, '101', '8', () => true))
  await assert.rejects(revalidatedDraft(read, '101', '7', () => false))
  await assert.rejects(revalidatedDraft(async () => { throw new Error('permission revoked') }, '101', '7', () => true))
})

test('a delayed clipboard denial cannot open a different customer draft', async () => {
  let current = true, rejectClipboard
  const pending = copyOrFallback('Authorized A', () => new Promise((resolve, reject) => { rejectClipboard = reject }), () => current)
  current = false
  rejectClipboard(new Error('permission denied'))
  assert.equal(await pending, null)
  assert.deepEqual(await copyOrFallback('Authorized A', async () => { throw new Error('denied') }, () => true),
    { copied: false, text: 'Authorized A' })
})
