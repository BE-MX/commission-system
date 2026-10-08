import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'
import { useListPage } from '../src/composables/useListPage.js'

const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundRecords.js', import.meta.url), 'utf8')
  .replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('ref', 'useRoute', 'useListPage', 'listOutboundRecords', `${source}; return useOutboundRecords`)

test('status filters submit together, persist on paging/sort and reset to all records', async () => {
  const requests = []
  const state = factory(ref, () => ({ query: {} }), useListPage, async params => {
    requests.push(params)
    return { data: { items: [], total: 100 } }
  })()
  await state.fetchList()
  assert.deepEqual(requests.at(-1), { page: 1, page_size: 20 })
  state.searchForm.outboundState = 'ready'
  state.searchForm.inspectionStatus = 'draft'
  state.searchForm.keyword = 'customer'
  state.searchForm.dateRange = ['2026-10-01', '2026-10-08']
  state.page.value = 3
  assert.equal(state.hasPendingSearch.value, true)
  await state.handleSearch()
  assert.deepEqual(requests.at(-1), { page: 1, page_size: 20, keyword: 'customer',
    outbound_state: 'ready', inspection_status: 'draft', date_from: '2026-10-01', date_to: '2026-10-08' })
  state.searchForm.inspectionStatus = 'submitted'
  await state.handlePageChange(2)
  assert.equal(requests.at(-1).page, 2)
  assert.equal(requests.at(-1).inspection_status, 'draft')
  await state.handleSortChange({ sort_field: 'outbound_no', sort_order: 'asc' })
  assert.equal(requests.at(-1).page, 1)
  assert.equal(requests.at(-1).inspection_status, 'draft')
  await state.handleSearch()
  assert.equal(requests.at(-1).inspection_status, 'submitted')
  await state.handleReset()
  assert.equal(state.searchForm.outboundState, '')
  assert.equal(state.searchForm.inspectionStatus, '')
  assert.equal(state.hasPendingSearch.value, false)
  assert.deepEqual(requests.at(-1), { page: 1, page_size: 20, sort_field: 'outbound_no', sort_order: 'asc' })
})

test('clearing one status removes only that API filter after querying', async () => {
  const requests = []
  const state = factory(ref, () => ({ query: {} }), useListPage, async params => {
    requests.push(params)
    return { data: { items: [], total: 0 } }
  })()
  state.searchForm.outboundState = 'ready'
  state.searchForm.inspectionStatus = 'none'
  await state.handleSearch()
  assert.equal(requests.at(-1).inspection_status, 'none')
  state.searchForm.outboundState = ''
  await state.handleSearch()
  assert.equal(requests.at(-1).outbound_state, undefined)
  assert.equal(requests.at(-1).inspection_status, 'none')
})
