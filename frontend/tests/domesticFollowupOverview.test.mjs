import test from 'node:test'
import assert from 'node:assert/strict'
import { useFollowupOverview } from '../src/views/domestic_followup/composables/useFollowupOverview.js'

test('overview requests visible scope and commits filters across pagination, refresh and reset', async () => {
  const calls = []
  const state = useFollowupOverview({ followups: async (params, options) => {
    calls.push({ ...params })
    assert.ok(options.signal instanceof AbortSignal)
    return { items: [{ id: 7, author_name: 'Sales A' }], total: 41 }
  } })
  state.searchForm.keyword = '  客户  '
  state.searchForm.author_user_id = 12
  state.searchForm.date_from = '2026-11-01'
  state.searchForm.date_to = '2026-11-04'
  await state.handleSearch()
  assert.equal(calls[0].mine, undefined)
  assert.equal(calls[0].keyword, '客户')
  assert.equal(calls[0].author_user_id, 12)
  assert.equal(calls[0].date_to, '2026-11-04')
  state.searchForm.keyword = 'not yet applied'
  await state.handlePageChange(2)
  assert.equal(calls[1].keyword, '客户')
  assert.equal(calls[1].page, 2)
  await state.fetchList()
  assert.equal(calls[2].author_user_id, 12)
  await state.handleReset()
  assert.equal(calls[3].page, 1)
  for (const field of ['keyword', 'author_user_id', 'date_from', 'date_to']) assert.equal(calls[3][field], undefined)
})

test('reversed dates report actionable errors and issue no request', async () => {
  let calls = 0
  const state = useFollowupOverview({ followups: async () => { calls++; return { items: [], total: 0 } } })
  state.searchForm.date_from = '2026-11-04'
  state.searchForm.date_to = '2026-11-01'
  assert.equal(await state.handleSearch(), false)
  assert.match(state.errorMessage.value, /开始日期不能晚于结束日期/)
  assert.equal(calls, 0)
  await state.handleReset()
  assert.equal(calls, 1)
})

test('a late previous query cannot replace the newest overview or its loading state', async () => {
  const requests = []
  const state = useFollowupOverview({ followups: (params, options) => new Promise(resolve => {
    requests.push({ params, options, resolve })
  }) })
  const first = state.fetchList()
  state.searchForm.keyword = 'latest'
  const second = state.handleSearch()
  assert.equal(requests[0].options.signal.aborted, true)
  requests[1].resolve({ items: [{ id: 'latest' }], total: 1 })
  await second
  requests[0].resolve({ items: [{ id: 'old' }], total: 100 })
  await first
  assert.equal(state.list.value[0].id, 'latest')
  assert.equal(state.total.value, 1)
  assert.equal(state.loading.value, false)
})

test('refresh failure keeps rows and offers a retry that recovers', async () => {
  let fail = false
  const state = useFollowupOverview({ followups: async () => {
    if (fail) throw new Error('连接失败')
    return { items: [{ id: 1 }], total: 1 }
  } })
  await state.fetchList()
  fail = true
  assert.equal(await state.fetchList(), false)
  assert.equal(state.list.value[0].id, 1)
  assert.equal(state.isStale.value, true)
  fail = false
  assert.equal(await state.fetchList(), true)
  assert.equal(state.errorMessage.value, '')
})
