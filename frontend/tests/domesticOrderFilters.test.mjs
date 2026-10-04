import test from 'node:test'
import assert from 'node:assert/strict'
import { useListPage } from '../src/composables/useListPage.js'
import { buildOrderListParams, emptyAdvancedFilters, useDomesticOrderFilters } from '../src/views/domestic/composables/useDomesticOrderFilters.js'

function setup() {
  const requests = []
  const state = useListPage(async params => {
    requests.push(buildOrderListParams(params))
    return { items: [], total: 100 }
  }, { immediate: false, searchForm: { keyword: 'PO', customer_name: '莱莎', owner_user_id: '', status: 0, order_kind: 'business', ...emptyAdvancedFilters() } })
  const filters = useDomesticOrderFilters(state.searchForm, () => ({ order_channels: [{ value: 'cash', label: '现金单' }] }), state.handleSearch, () => state.appliedSearchForm.value)
  return { form: state.searchForm, state, filters, requests, calls: () => requests.length }
}

test('customer and order queries combine with draft status, dates and advanced filters', () => {
  assert.deepEqual(buildOrderListParams({ page: 2, page_size: 20, keyword: ' PO ', customer_name: ' 莱莎 ',
    status: 0, order_channel: 'cash', dateRange: ['2026-09-01', '2026-09-11'] }), {
    page: 2, page_size: 20, keyword: 'PO', customer_name: '莱莎', status: 0,
    order_channel: 'cash', date_start: '2026-09-01', date_end: '2026-09-11',
  })
  assert.deepEqual(buildOrderListParams({ page: 1, page_size: 20, keyword: ' ', status: '', dateRange: null }), { page: 1, page_size: 20 })
  assert.deepEqual(buildOrderListParams({ page: 1, page_size: 20, owner_user_id: 7, dateRange: [] }), { page: 1, page_size: 20, owner_user_id: 7 })
})

test('header sorting forwards both parameters and clearing omits them', () => {
  assert.deepEqual(buildOrderListParams({ page: 1, page_size: 20, sort_field: 'order_date', sort_order: 'desc' }), {
    page: 1, page_size: 20, sort_field: 'order_date', sort_order: 'desc',
  })
  assert.deepEqual(buildOrderListParams({ page: 1, page_size: 20, sort_field: '', sort_order: '' }), {
    page: 1, page_size: 20,
  })
})

test('advanced fields and current-query tags change only after an explicit query', async () => {
  const { form, state, filters, requests } = setup()
  form.order_channel = 'cash'
  form.dateRange = ['2026-09-01', '2026-09-11']
  await state.handlePageChange(2)
  assert.equal(requests.at(-1).order_channel, undefined)
  assert.equal(requests.at(-1).date_start, undefined)
  assert.deepEqual(filters.advancedTags.value, [])
  await state.handleSearch()
  assert.equal(requests.at(-1).page, 1)
  assert.equal(requests.at(-1).order_channel, 'cash')
  assert.equal(filters.advancedTags.value.length, 2)
  form.dateRange[0] = '2026-08-01'
  assert.equal(filters.advancedTags.value[0].label, '下单日期：2026-09-01 至 2026-09-11')
})

test('tag removal and reset query once, clear advanced fields and preserve the current tab', async () => {
  const { form, state, filters, requests, calls } = setup()
  form.order_channel = 'cash'
  await state.handleSearch()
  assert.equal(calls(), 1)
  assert.deepEqual(filters.advancedTags.value, [{ key: 'order_channel', label: '订单渠道：现金单' }])
  await filters.removeAdvanced('order_channel')
  assert.equal(calls(), 2)
  assert.deepEqual(filters.advancedTags.value, [])
  form.owner_user_id = 7
  form.dateRange = ['2026-09-01', '2026-09-11']
  state.page.value = 4
  await filters.resetFilters()
  assert.equal(calls(), 3)
  assert.equal(form.order_kind, 'business')
  assert.equal(form.customer_name, '')
  assert.equal(form.owner_user_id, '')
  assert.equal(form.keyword, '')
  assert.equal(form.status, '')
  assert.deepEqual(form.dateRange, [])
  assert.equal(requests.at(-1).page, 1)
  assert.equal(state.hasPendingSearch.value, false)
})

test('production queries exclude business conditions but keep customer and date queries', async () => {
  const { form, state, filters, requests } = setup()
  form.order_kind = 'production'
  form.customer_source = 'referral'
  form.order_channel = 'cash'
  form.dateRange = ['2026-09-01', '2026-09-11']
  await state.handleSearch()
  assert.equal(filters.advancedTags.value.length, 1)
  const params = requests.at(-1)
  assert.equal(params.order_channel, undefined)
  assert.equal(params.customer_source, undefined)
  assert.equal(params.customer_name, '莱莎')
  assert.equal(params.date_end, '2026-09-11')
})
