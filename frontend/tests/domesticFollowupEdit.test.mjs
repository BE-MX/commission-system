import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { useFollowupEditor } from '../src/views/domestic_followup/composables/useFollowupEditor.js'
import { useFollowupWorkbenchData } from '../src/views/domestic_followup/composables/useFollowupWorkbenchData.js'
import { mayEditFollowup, recordToEditForm, canRemoveEditItem } from '../src/views/domestic_followup/followupEdit.js'
import { revisionChanges } from '../src/views/domestic_followup/followupHistory.js'

const record = () => ({ id: 1, version: 2, can_edit: true, author_user_id: 7, customer_id: 1,
  result_code: '有效沟通',
  raw_text: '原文', summary: '摘要', followup_date: '2026-11-01', channel: '微信',
  state_changes: ['稳定没变化'], next_date: '2026-11-09', next_plan: '原计划', next_method: '电话',
  attachments: [{ id: 11, seq: 1, file_name: 'original.png' }], items: [
    { id: 8, kind: 'content', text: '要点', status: null, origin: 'user' },
    { id: 9, kind: 'issue', text: '色差', status: 'resolved', resolution: '已补发', handler_user_id: 9 },
  ] })

test('edit permissions allow author with write and super_admin, not read_all alone', () => {
  assert.equal(mayEditFollowup({ id: 7, permissions: ['domestic_followup:write'] }, record()), true)
  assert.equal(mayEditFollowup({ id: 8, roles: ['super_admin'] }, record()), true)
  assert.equal(mayEditFollowup({ id: 8, permissions: ['domestic_followup:read_all', 'domestic_followup:write'] }, record()), false)
  assert.equal(mayEditFollowup({ id: 7, permissions: [] }, record()), false)
})

test('form retains item identity and original attachments without assigning resolved state', () => {
  const row = record(), form = recordToEditForm(row)
  assert.equal(form.items[1].id, 9)
  assert.equal(form.items[1].handler_user_id, 9)
  assert.equal(form.items[1].status, undefined)
  assert.equal(form.customer_id, undefined)
  form.items[0].text = '更正'
  assert.equal(row.items[0].text, '要点')
  assert.equal(canRemoveEditItem(form.items[1], row), false)
  assert.equal(canRemoveEditItem({ kind: 'issue' }, row), true)
})

test('save requires reason and emits a full editable payload then refreshes caller', async () => {
  const saved = [], calls = []
  const editor = useFollowupEditor({ followup: async () => record(), dicts: async () => ({}),
    editFollowup: async (id, payload) => { calls.push([id, payload]); return { id, version: 3 } } }, row => saved.push(row))
  await editor.open(1)
  assert.equal(await editor.save(), false)
  assert.match(editor.error.value, /修改原因/)
  editor.form.value.reason = '修正'
  editor.form.value.items.push({ kind: 'content', text: '新要点', key: 'local-only' })
  assert.equal(await editor.save(), true)
  assert.equal(calls[0][1].version, 2)
  assert.equal(calls[0][1].items[2].key, undefined)
  assert.equal(saved[0].version, 3)
  assert.equal(editor.visible.value, false)
})

test('editing a legacy record requires an outcome before sending a request', async () => {
  let calls = 0
  const editor = useFollowupEditor({ followup: async () => ({ ...record(), result_code: null }),
    dicts: async () => ({}), editFollowup: async () => { calls++; return record() } })
  await editor.open(1)
  editor.form.value.reason = '补充本次结果'
  assert.equal(await editor.save(), false)
  assert.equal(editor.error.value, '请选择本次结果')
  assert.equal(calls, 0)
  editor.form.value.result_code = '未回复'
  assert.equal(await editor.save(), true)
  assert.equal(calls, 1)
})

test('stale conflict preserves user text and prevents silent overwrite until reload', async () => {
  let currentVersion = 2
  const editor = useFollowupEditor({ followup: async () => ({ ...record(), version: currentVersion }), dicts: async () => ({}),
    editFollowup: async () => { throw { response: { status: 409, data: { detail: '记录已修改' } } } } })
  await editor.open(1)
  editor.form.value.raw_text = '未保存内容'
  editor.form.value.reason = '更正'
  assert.equal(await editor.save(), false)
  assert.equal(editor.form.value.raw_text, '未保存内容')
  assert.equal(editor.conflict.value, true)
  currentVersion = 3
  await editor.reload()
  assert.equal(editor.form.value.version, 3)
  assert.equal(editor.conflict.value, false)
})

test('ambiguous transport failure retries the exact same request instead of duplicating edits', async () => {
  const calls = []
  const editor = useFollowupEditor({ followup: async () => record(), dicts: async () => ({}), editFollowup: async (id, body) => {
    calls.push(body)
    if (calls.length === 1) throw new Error('response lost')
    return { id, version: 3 }
  } })
  await editor.open(1)
  editor.form.value.reason = '更正'
  editor.form.value.raw_text = '第一次'
  await editor.save()
  assert.equal(editor.uncertain.value, true)
  editor.form.value.raw_text = '模拟外部更改'
  await editor.save()
  assert.deepEqual(calls[0], calls[1])
  assert.equal(calls[1].raw_text, '第一次')
})

test('late editor load cannot reopen or replace a closed editor', async () => {
  let resolve
  const editor = useFollowupEditor({ followup: () => new Promise(done => { resolve = done }), dicts: async () => ({}) })
  const opening = editor.open(1)
  editor.close()
  resolve(record())
  await opening
  assert.equal(editor.visible.value, false)
  assert.equal(editor.record.value, null)
})

test('potential checkbox applies to summary, both task windows and paginated mine records', async () => {
  const calls = [], scope = ref(false)
  const state = useFollowupWorkbenchData({
    summary: async params => { calls.push(['summary', params]); return { plan: params.potential_only ? 1 : 2 } },
    tasks: async params => { calls.push(['tasks', params]); return { items: [{ id: params.potential_only ? 'potential' : 'all' }] } },
    followups: async params => { calls.push(['records', params]); return { items: [{ id: 'mine' }], total: 1 } }, drafts: async () => [],
  }, scope)
  await state.loadTasks()
  await state.loadRecords(3)
  scope.value = true
  state.resetScope()
  assert.deepEqual(state.records.items, [])
  assert.equal(state.records.page, 1)
  await state.loadTasks()
  await state.loadRecords(1)
  assert.equal(state.summary.plan, 1)
  assert.equal(state.filtered.value.due[0].id, 'potential')
  const latest = calls.slice(-4)
  assert.equal(latest.every(([, params]) => params.potential_only === true), true)
  assert.equal(latest[3][1].mine, true)
})

test('scope switch ignores late records from the old checkbox selection', async () => {
  const requests = [], scope = ref(false)
  const state = useFollowupWorkbenchData({ followups: params => new Promise(resolve => requests.push({ params, resolve })) }, scope)
  const old = state.loadRecords()
  scope.value = true
  state.resetScope()
  const latest = state.loadRecords()
  requests[1].resolve({ items: [{ id: 'potential' }], total: 1 })
  await latest
  requests[0].resolve({ items: [{ id: 'established' }], total: 10 })
  await old
  assert.equal(state.records.items[0].id, 'potential')
  assert.equal(state.records.total, 1)
})

test('history presents record, task and attachment changes with business labels', () => {
  const before = { raw_text: '旧原文', items: [{ id: 1, kind: 'issue', text: '色差' }],
    tasks: [{ id: 1, title: '回访', status: 'todo', due_date: '2026-11-01' }], attachments: [{ id: 1, file_name: 'old.png' }] }
  const after = { ...before, raw_text: '新原文', items: [], tasks: [{ ...before.tasks[0], status: 'cancelled' }], attachments: [] }
  const changes = revisionChanges({ before, after })
  assert.equal(changes.find(c => c.label === '跟进原文').after, '新原文')
  assert.match(changes.find(c => c.label === '关联待办').after, /已取消/)
  assert.equal(changes.find(c => c.label === '截图').before, 'old.png')
})
