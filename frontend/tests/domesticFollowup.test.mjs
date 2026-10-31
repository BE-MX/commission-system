import test from 'node:test'
import assert from 'node:assert/strict'
import {
  draftToForm, emptyForm, formToPayload, imageFilesFromClipboard, mergeManualFields, nextBasisHint, taskDueLabel,
  weekdayLabel, clipboardHasText, imageFilesFromDrop,
} from '../src/views/domestic_followup/followupDraft.js'

const TODAY = '2026-10-30'

test('weekdayLabel maps ISO calendar dates to weekday labels', () => {
  assert.equal(weekdayLabel('2026-10-30'), '周五')
  assert.equal(weekdayLabel('2026-11-02'), '周一')
  assert.equal(weekdayLabel(''), '')
})

test('draftToForm maps AI result into editable sections', () => {
  const form = draftToForm({
    id: 7, version: 1, customer_id: null, followup_date: TODAY, channel: '微信', raw_text: '原文',
    ai_result: {
      customer_id: 12, customer_confidence: 0.9, chat_title: '均哥', summary: '想开新号', channel: '电话',
      items: [
        { kind: 'content', text: '月销 13 万', origin: 'user' },
        { kind: 'issue', text: '退货率高', category: '售后退换', severity: '紧急', origin: 'user' },
        { kind: 'suggestion', text: '要短视频', category: '产品需求', severity: '一般', origin: 'ai_inferred' },
      ],
      state_changes: ['店里增加短视频'],
      next: { date: '2026-11-02', weekday: '周一', expression: '下周一', basis: 'mismatch', method: '电话', plan: '问进度' },
      unreadable: ['语音 2″'],
    },
  }, TODAY)
  assert.equal(form.customer_id, 12)
  assert.equal(form.channel, '微信')  // 用户在输入步选的沟通方式优先于 AI
  assert.deepEqual(form.contents.map(i => i.text), ['月销 13 万'])
  assert.equal(form.issues[0].severity, '紧急')
  assert.equal(form.suggestions[0].origin, 'ai_inferred')
  assert.equal(form.next_date, '2026-11-02')
  assert.equal(form.nextBasis, 'mismatch')
  assert.deepEqual(form.unreadable, ['语音 2″'])
  assert.equal(form.version, 1)
})

test('draftToForm keeps manual customer over AI hint and tolerates missing ai_result', () => {
  const form = draftToForm({ id: 1, version: 1, customer_id: 5, followup_date: TODAY, ai_result: { customer_id: 9 } }, TODAY)
  assert.equal(form.customer_id, 5)
  const bare = draftToForm({ id: 2, version: 1, followup_date: TODAY, ai_result: null }, TODAY)
  assert.deepEqual(bare.issues, [])
})

test('formToPayload flattens sections, drops blanks and keeps record_only', () => {
  const form = { ...emptyForm(TODAY), customer_id: 3, summary: ' s ' }
  form.contents = [{ text: '要点', origin: 'user' }, { text: '  ', origin: 'user' }]
  form.issues = [{ text: '色差', category: '色差', severity: '一般', origin: 'user', record_only: false }]
  form.suggestions = [{ text: '想要素材', category: '产品需求', severity: '一般', origin: 'user', record_only: true }]
  form.closeTaskIds = [11]
  form.resolvedItems = [{ item_id: 4, resolution: '已补发' }]
  const payload = formToPayload(form)
  assert.deepEqual(payload.items.map(i => [i.kind, i.text, i.record_only]),
    [['content', '要点', false], ['issue', '色差', false], ['suggestion', '想要素材', true]])
  assert.equal(payload.summary, 's')
  assert.deepEqual(payload.close_task_ids, [11])
  assert.deepEqual(payload.resolved_items, [{ item_id: 4, status: 'resolved', resolution: '已补发' }])
  assert.equal(payload.next_date, null)
})

test('imageFilesFromClipboard returns only image files', () => {
  const png = { type: 'image/png', name: 'a.png' }
  const event = { clipboardData: { items: [
    { kind: 'file', type: 'image/png', getAsFile: () => png },
    { kind: 'string', type: 'text/plain', getAsFile: () => null },
  ] } }
  assert.deepEqual(imageFilesFromClipboard(event), [png])
  assert.deepEqual(imageFilesFromClipboard({}), [])
})

test('taskDueLabel and nextBasisHint', () => {
  assert.equal(taskDueLabel({ due_date: TODAY, overdue_days: 0 }, TODAY), '今天')
  assert.equal(taskDueLabel({ due_date: '2026-10-27', overdue_days: 3 }, TODAY), '逾期 3 天')
  assert.equal(taskDueLabel({ due_date: '2026-11-02', overdue_days: 0 }, TODAY), '11-02 周一')
  assert.match(nextBasisHint({ nextBasis: 'mismatch', nextExpression: '下周一', next_date: '2026-11-02' }), /已按「下周一」改为 11-02/)
  assert.equal(nextBasisHint({ nextBasis: 'parsed' }), '')
})

test('draftToForm falls back to AI channel only when user left it blank', () => {
  const form = draftToForm({ id: 3, version: 1, channel: null, followup_date: TODAY, ai_result: { channel: '电话' } }, TODAY)
  assert.equal(form.channel, '电话')
})

test('mergeManualFields keeps hand-filled next fields and channel over AI result', () => {
  const ai = draftToForm({
    id: 4, version: 1, channel: null, followup_date: TODAY,
    ai_result: { channel: '电话', next: { date: '2026-11-02', expression: '下周一', basis: 'mismatch', method: '电话', plan: 'AI 计划' } },
  }, TODAY)
  const merged = mergeManualFields(ai, { channel: '微信', next_date: '2026-11-05', next_plan: ' 送样 ', next_method: '上门' })
  assert.equal(merged.channel, '微信')
  assert.equal(merged.next_date, '2026-11-05')
  assert.equal(merged.next_plan, ' 送样 ')
  assert.equal(merged.next_method, '上门')
  assert.equal(merged.nextBasis, 'none')  // 手填日期不再挂 AI 纠正提示
  assert.equal(merged.nextExpression, null)
})

test('mergeManualFields leaves AI values when manual fields are blank', () => {
  const ai = draftToForm({
    id: 5, version: 1, followup_date: TODAY,
    ai_result: { next: { date: '2026-11-02', expression: '下周一', basis: 'parsed', method: '电话', plan: '问进度' } },
  }, TODAY)
  const merged = mergeManualFields(ai, { channel: null, next_date: null, next_plan: '  ', next_method: '' })
  assert.equal(merged.next_date, '2026-11-02')
  assert.equal(merged.next_plan, '问进度')
  assert.equal(merged.next_method, '电话')
  assert.equal(merged.nextExpression, '下周一')
  assert.equal(mergeManualFields(ai, null), ai)
})

test('imageFilesFromClipboard callers can detect mixed text clipboard', () => {
  assert.equal(clipboardHasText({ clipboardData: { types: ['text/plain', 'Files'] } }), true)
  assert.equal(clipboardHasText({ clipboardData: { types: ['Files'] } }), false)
  assert.equal(clipboardHasText({}), false)
})

test('imageFilesFromDrop returns only dropped image files', () => {
  const png = { type: 'image/png', name: 'a.png' }
  const txt = { type: 'text/plain', name: 'a.txt' }
  assert.deepEqual(imageFilesFromDrop({ dataTransfer: { files: [png, txt] } }), [png])
  assert.deepEqual(imageFilesFromDrop({}), [])
})

test('mergeManualFields takes the whole next block from user when user set next_date', () => {
  const ai = draftToForm({
    id: 6, version: 1, followup_date: TODAY,
    ai_result: { next: { date: '2026-11-02', expression: '下周一', basis: 'parsed', method: '电话', plan: '问进度' } },
  }, TODAY)
  const merged = mergeManualFields(ai, { next_date: '2026-11-06', next_plan: '', next_method: null })
  assert.equal(merged.next_date, '2026-11-06')
  assert.equal(merged.next_plan, '')  // 用户定了日期：方式和内容也以用户为准，不拼 AI 的
  assert.equal(merged.next_method, null)
  const planOnly = mergeManualFields(ai, { next_date: null, next_plan: '带样品', next_method: null })
  assert.equal(planOnly.next_date, '2026-11-02')
  assert.equal(planOnly.next_plan, '带样品')
  assert.equal(planOnly.next_method, '电话')
})
