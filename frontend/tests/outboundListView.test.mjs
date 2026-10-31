import test from 'node:test'
import assert from 'node:assert/strict'
import { effectScope, nextTick, reactive } from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useOutboundListView } from '../src/views/shipping/composables/useOutboundListView.js'
import { emptyOutboundFilters, outboundFilterSummary, outboundListQuery, outboundSortSummary, readOutboundListState } from '../src/views/shipping/composables/outboundListState.js'

function fixture(query = {}) {
  const scope = effectScope(), route = reactive({ path: '/shipping/outbound', query, hash: '' }), requests = [], navigations = []
  const router = Object.fromEntries(['push', 'replace'].map(method => [method, async location => { navigations.push({ method, ...location }); route.path = location.path; route.query = location.query; return undefined }]))
  let list, view
  scope.run(() => {
    list = useListPage(async params => { requests.push(params); return { items: [params.keyword || 'all'], total: 200 } }, { immediate: false, searchForm: emptyOutboundFilters() })
    view = useOutboundListView(list, route, router)
  })
  return { route, router, list, view, requests, navigations, stop: () => { view.stop(); scope.stop() } }
}
const settle = async () => { await nextTick(); await nextTick(); await nextTick() }

test('initial URL restores all query fields, page, size and sorting before one initial read', async () => {
  const f = fixture({ keyword: 'ARK', outbound_state: 'ready', inspection_status: 'draft', date_from: '2026-10-01', date_to: '2026-10-20', page: '2', page_size: '50', sort_field: 'outbound_no', sort_order: 'desc' })
  assert.equal(f.requests.length, 0)
  await f.list.fetchList(); await settle()
  assert.equal(f.requests.length, 1)
  assert.deepEqual(f.requests[0], { keyword: 'ARK', orderId: '', outboundState: 'ready', inspectionStatus: 'draft', dateRange: ['2026-10-01', '2026-10-20'], page: 2, page_size: 50, sort_field: 'outbound_no', sort_order: 'desc' })
  f.stop()
})
test('draft edits do not enter URL, summary or page reads; submission publishes once without a second fetch', async () => {
  const f = fixture({ inspection_status: 'draft' })
  f.list.searchForm.keyword = 'unsubmitted'
  f.list.searchForm.dateRange = ['2026-09-01', '2026-09-30']
  await settle()
  assert.equal(f.navigations.length, 0)
  await f.list.handlePageChange(3); await settle()
  assert.equal(f.requests.length, 1)
  assert.equal(f.requests[0].keyword, '')
  assert.deepEqual(f.route.query, { inspection_status: 'draft', page: '3' })
  assert.equal(f.list.hasPendingSearch.value, true)
  const summary = outboundFilterSummary(f.list.appliedSearchForm.value, {}, { draft: '检验中' })
  assert.deepEqual(summary.map(x => x.key), ['inspectionStatus'])
  await f.list.handleSearch(); await settle()
  assert.equal(f.requests.length, 2)
  assert.equal(f.route.query.keyword, 'unsubmitted')
  assert.equal(f.route.query.date_from, '2026-09-01')
  assert.equal(f.route.query.page, undefined)
  f.stop()
})
test('back and forward restore committed views atomically and removing one filter never applies another draft', async () => {
  const f = fixture({ keyword: 'saved', outbound_state: 'ready', page: '3' })
  await f.list.fetchList()
  f.route.query = { keyword: 'older', inspection_status: 'submitted', page: '2', page_size: '50' }
  await settle()
  assert.equal(f.requests.length, 2)
  assert.equal(f.requests.at(-1).page, 2)
  assert.equal(f.requests.at(-1).keyword, 'older')
  f.list.searchForm.keyword = 'do not submit'
  f.view.removeFilter('inspectionStatus'); await settle()
  assert.equal(f.requests.length, 3)
  assert.equal(f.requests.at(-1).keyword, 'older')
  assert.equal(f.requests.at(-1).inspectionStatus, '')
  assert.equal(f.list.searchForm.keyword, 'do not submit')
  assert.equal(f.list.hasPendingSearch.value, true)
  assert.equal(f.route.query.page, undefined)
  await f.list.handleReset(); await settle()
  assert.equal(f.list.appliedSearchForm.value.keyword, '')
  assert.deepEqual(f.route.query, { page_size: '50' })
  f.stop()
})
test('problem deep links reset unrelated conditions and re-query when focus changes', async () => {
  const f = fixture({ outbound_state: 'ready', inspection_status: 'draft', page: '3' })
  f.route.query = { keyword: 'CK-10', order_id: '42', problem: 'sync', problem_focus: '1' }
  await settle()
  assert.equal(f.requests.length, 1)
  assert.equal(f.requests[0].outboundState, '')
  assert.equal(f.requests[0].inspectionStatus, '')
  assert.equal(f.requests[0].orderId, '42')
  f.route.query = { ...f.route.query, problem_focus: '2' }; await settle()
  assert.equal(f.requests.length, 2)
  f.stop()
})
test('returning to an unfiltered history URL restores empty conditions; unrelated routes never receive list parameters', async () => {
  const f = fixture({ keyword: 'saved', page: '3' })
  f.route.path = '/dashboard'; f.route.query = {}; await settle()
  f.list.searchForm.keyword = 'draft'
  assert.equal(f.navigations.length, 0)
  f.route.path = '/shipping/outbound'; await settle()
  assert.deepEqual(f.route.query, {})
  assert.equal(f.list.appliedSearchForm.value.keyword, '')
  assert.equal(f.list.page.value, 1)
  assert.equal(f.requests.length, 1)
  f.route.query = { keyword: 'saved', page: '3' }; await settle()
  assert.equal(f.list.appliedSearchForm.value.keyword, 'saved')
  assert.equal(f.list.page.value, 3)
  assert.equal(f.requests.length, 2)
  f.stop()
})
test('URL restores reject repeated parameters, unknown enums/sort and invalid dates or pagination', () => {
  const state = readOutboundListState({ keyword: ['one', 'two'], order_id: null, outbound_state: ['ready'], inspection_status: 'admin', date_from: '2026-02-31', date_to: '2026-03-03', page: '-2', page_size: '500', sort_field: 'DROP TABLE', sort_order: 'asc' })
  assert.deepEqual(state, { searchForm: emptyOutboundFilters(), page: 1, pageSize: 20, sortParams: {} })
  const valid = readOutboundListState({ keyword: '示例客户', inspection_status: 'none', page: '2' })
  assert.deepEqual(outboundListQuery(valid, { unrelated: 'keep', keyword: 'old' }), { unrelated: 'keep', keyword: '示例客户', inspection_status: 'none', page: '2' })
})

test('sort summary remains visible for hidden or non-column fields and clearing sorting preserves drafts', async () => {
  const f = fixture({ sort_field: 'order_id', sort_order: 'desc' })
  assert.deepEqual(outboundSortSummary(f.list.appliedSort.value), [{ key: 'sort', label: '排序', value: '订单 ID · 降序' }])
  f.list.searchForm.keyword = 'draft'
  await f.list.handleSortChange({}); await settle()
  assert.equal(f.requests.length, 1)
  assert.deepEqual(f.route.query, {})
  assert.deepEqual(outboundSortSummary(f.list.appliedSort.value), [])
  assert.equal(f.list.searchForm.keyword, 'draft')
  assert.equal(f.requests[0].keyword, '')
  f.stop()
})
