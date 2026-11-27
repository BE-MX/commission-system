import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isIsoDate, latestReview, localClock, reviewSections, sortProspects, threadCard, validateProspectForm } from '../src/views/client_desk/unlinkedLeadsModel.js'

// 2026-11-25 02:30 UTC is 10:30 in Shanghai (working) and 21:30 on the 24th in New York (off hours).
const NOW = new Date('2026-11-25T02:30:00Z')

test('local clock shows working hours in the lead timezone and hides when no timezone is known', () => {
  assert.deepEqual(localClock('Asia/Shanghai', NOW), { hm: '10:30', working: true, text: '当地 10:30 · 工作时段' })
  assert.equal(localClock('America/New_York', NOW).text, '当地 21:30 · 非工作时段')
  assert.equal(localClock(null, NOW), null)
  assert.equal(localClock('Not/AZone', NOW), null)
})

test('prospect form requires both the follow-up date and the promise text', () => {
  const empty = validateProspectForm({})
  assert.equal(empty.ok, false)
  assert.deepEqual(Object.keys(empty.errors).sort(), ['next_followup_date', 'next_followup_remark'])

  const blankRemark = validateProspectForm({ next_followup_date: '2026-11-28', next_followup_remark: '   ' })
  assert.equal(blankRemark.ok, false)
  assert.deepEqual(Object.keys(blankRemark.errors), ['next_followup_remark'])

  const badDate = validateProspectForm({ next_followup_date: '2026-02-30', next_followup_remark: '发样' })
  assert.equal(badDate.errors.next_followup_date, '日期格式不正确')

  const ok = validateProspectForm({ next_followup_date: '2026-11-28', next_followup_remark: '  周五前发实拍视频 ' })
  assert.equal(ok.ok, true)
  assert.deepEqual(ok.payload, { next_followup_date: '2026-11-28', next_followup_remark: '周五前发实拍视频' })
})

test('iso date check rejects non-existent days and other formats', () => {
  assert.equal(isIsoDate('2026-11-25'), true)
  assert.equal(isIsoDate('2024-02-29'), true)
  assert.equal(isIsoDate('2026-02-29'), false)
  assert.equal(isIsoDate('2026/11/25'), false)
  assert.equal(isIsoDate(undefined), false)
})

test('prospects sort by follow-up date with undated items last, without mutating input', () => {
  const input = [
    { id: 1, next_followup_date: '2026-12-02' },
    { id: 2, next_followup_date: null },
    { id: 3, next_followup_date: '2026-11-28' },
    { id: 4, next_followup_date: '2026-11-28' },
  ]
  const snapshot = input.map(item => item.id)
  assert.deepEqual(sortProspects(input).map(item => item.id), [3, 4, 1, 2])
  assert.deepEqual(input.map(item => item.id), snapshot)
})

test('thread card with no analysis yet shows a neutral pending state and no draft', () => {
  const card = threadCard({ id: 7, channel: 'tm', display_name: 'Buyer A', company_hint: 'Glow Studio', status: 'active', run: null, match: null, local_timezone: null })
  assert.equal(card.analysisPending, true)
  assert.equal(card.draft, '')
  assert.equal(card.draftWarning, '')
  assert.equal(card.clock, null)
  assert.equal(card.channelLabel, 'TM 询盘')
  assert.equal(card.followup, null)
})

test('WhatsApp threads carry their own channel label, masked number and scan schedule', () => {
  const tm = threadCard({ id: 1, channel: 'tm', status: 'active', run: null })
  const wa = threadCard({ id: 2, channel: 'whatsapp', display_name: 'Maria', company_hint: '+447****1234', status: 'active', run: null })
  assert.equal(wa.channelLabel, 'WhatsApp')
  assert.equal(wa.hint, '+447****1234')
  assert.match(tm.pendingHint, /06:45/)
  assert.match(wa.pendingHint, /每小时/)
})

test('thread card flags drafts that need price or lead-time review and maps the weak match', () => {
  const card = threadCard({
    id: 8, channel: 'tm', display_name: 'Buyer B', company_hint: '', status: 'active',
    run: { one_line_summary: '问了价格', missing_or_next_action: '补报价', breakthrough_angle: '样品', urgency: 'high', draft_message: '您好，{price}', needs_review: true },
    match: { company_id: 'c-9', name: '老客 X', hint: '同名公司', level: 'weak' },
    local_timezone: 'Europe/Paris',
  }, NOW)
  assert.equal(card.analysisPending, false)
  assert.equal(card.draftHint, '草稿中的占位符需先核对，再发送给客户')
  assert.equal(card.draftWarning, '含报价/交期，发送前请核对')
  assert.equal(card.urgency.label, '高')
  assert.deepEqual(card.match, { companyId: 'c-9', name: '老客 X', hint: '同名公司' })
  assert.ok(card.clock)
})

test('prospect card carries the follow-up date and promise text', () => {
  const card = threadCard({ id: 9, channel: 'tm', display_name: 'Buyer C', status: 'prospect', next_followup_date: '2026-11-28', next_followup_remark: '发实拍', run: null, match: null })
  assert.deepEqual(card.followup, { date: '2026-11-28', remark: '发实拍' })
})

test('review sections map each list to its row action and tolerate missing lists', () => {
  assert.deepEqual(reviewSections(null), [])
  const sections = reviewSections({
    missed_tasks: [{ thread_id: 1, title: '未回报价', evidence: '第3天未回', suggested_action: '今天回复' }],
    breakthrough_leads: [],
    likely_existing_customers: [{ thread_id: 2, why: '同域名', matched_company_id: 'c-1' }, { thread_id: 3, why: '无匹配' }],
    cleanup_candidates: [{ thread_id: 4, reason: '供应商推销' }],
  })
  const byKey = Object.fromEntries(sections.map(s => [s.key, s]))
  assert.deepEqual(byKey.missed_tasks.rows.map(r => [r.threadId, r.action, r.sub]), [[1, 'open', '第3天未回 · 今天回复']])
  assert.equal(byKey.breakthrough_leads.rows.length, 0)
  assert.deepEqual(byKey.likely_existing_customers.rows.map(r => [r.action, r.matchedCompanyId]), [['bind', 'c-1'], ['bind', null]])
  assert.deepEqual(byKey.cleanup_candidates.rows.map(r => [r.action, r.actionLabel]), [['ignore', '不是客户']])
})

test('latest review is chosen by week start, not by API order', () => {
  const latest = latestReview([
    { id: 'old', week_start_date: '2026-11-09' },
    { id: 'new', week_start_date: '2026-11-16' },
  ])
  assert.equal(latest.id, 'new')
  assert.equal(latestReview([]), null)
})

async function createLeads(mockApi) {
  const { readFile } = await import('node:fs/promises')
  const { SourceTextModule, SyntheticModule } = await import('node:vm')
  const dependencies = {
    vue: await import('vue'),
    '@/api/clientDesk': { clientDeskApi: mockApi },
    '@/utils/feedback': {
      msgError: () => {}, msgSuccessText: () => {}, confirmAction: async () => {}, isFeedbackCancelled: () => false,
    },
    './deskController': await import('../src/views/client_desk/deskController.js'),
    './unlinkedLeadsModel': await import('../src/views/client_desk/unlinkedLeadsModel.js'),
  }
  const source = await readFile(new URL('../src/views/client_desk/useUnlinkedLeads.js', import.meta.url), 'utf8')
  const module = new SourceTextModule(source)
  await module.link(name => {
    const dependency = dependencies[name]
    return new SyntheticModule(Object.keys(dependency), function () {
      Object.entries(dependency).forEach(([key, value]) => this.setExport(key, value))
    })
  })
  await module.evaluate()
  return module.namespace.useUnlinkedLeads()
}

test('generating a weekly review reloads the full report before displaying it', async () => {
  const metadata = { id: 1, week_start_date: '2026-11-16', status: 'succeeded' }
  const report = {
    ...metadata, overview_md: '本周有一条待办',
    missed_tasks: [{ thread_id: '7', title: '回复', evidence: '询价', suggested_action: '核价' }],
  }
  const calls = []
  const leads = await createLeads({
    async unlinkedGenerateWeeklyReview() { calls.push('generate'); return metadata },
    async unlinkedWeeklyReviews() { calls.push('read'); return { items: [report] } },
  })
  await leads.generateReview()
  assert.deepEqual(calls, ['generate', 'read'])
  assert.equal(leads.review.value.overview_md, report.overview_md)
  assert.equal(leads.sections.value[0].rows[0].threadId, '7')
})

test('weekly review jump resolves a string thread ID in both lead views', async () => {
  const calls = []
  const leads = await createLeads({
    async unlinkedThreads({ view }) {
      calls.push(view)
      return { items: [{ id: view === 'active' ? 7 : 8 }] }
    },
  })
  await leads.actOnReviewRow({ action: 'open', threadId: '7' })
  assert.equal(leads.subView.value, 'pending')
  assert.equal(leads.focusId.value, '7')
  await leads.actOnReviewRow({ action: 'open', threadId: '8' })
  assert.equal(leads.subView.value, 'prospect')
  assert.equal(leads.focusId.value, '8')
  assert.deepEqual(calls, ['active', 'active', 'prospect'])
})
