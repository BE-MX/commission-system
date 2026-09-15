import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'
import { buildOrderListParams, emptyAdvancedFilters, useDomesticOrderFilters } from '../src/views/domestic/composables/useDomesticOrderFilters.js'

function setup() {
  const form = reactive({ keyword: 'PO', customer_name: '莱莎', status: 0, order_kind: 'business', ...emptyAdvancedFilters() })
  let calls = 0
  const filters = useDomesticOrderFilters(form, () => ({ order_channels: [{ value: 'cash', label: '现金单' }] }), () => { calls++ })
  return { form, filters, calls: () => calls }
}

test('customer and order queries combine with draft status, dates and advanced filters', () => {
  assert.deepEqual(buildOrderListParams({ page: 2, page_size: 20, keyword: ' PO ', customer_name: ' 莱莎 ',
    status: 0, order_channel: 'cash', dateRange: ['2026-09-01', '2026-09-11'] }), {
    page: 2, page_size: 20, keyword: 'PO', customer_name: '莱莎', status: 0,
    order_channel: 'cash', date_start: '2026-09-01', date_end: '2026-09-11',
  })
  assert.deepEqual(buildOrderListParams({ page: 1, page_size: 20, keyword: ' ', status: '', dateRange: null }), { page: 1, page_size: 20 })
})

test('cancel and clear in advanced dialog do not change current filters; reopening restores them', () => {
  const { form, filters, calls } = setup()
  form.order_channel = 'cash'
  form.dateRange = ['2026-09-01', '2026-09-11']
  filters.openAdvanced()
  filters.draft.dateRange[0] = '2026-08-01'
  filters.clearDraft()
  filters.advancedVisible.value = false
  assert.equal(form.order_channel, 'cash')
  assert.deepEqual(form.dateRange, ['2026-09-01', '2026-09-11'])
  assert.equal(calls(), 0)
  filters.openAdvanced()
  assert.equal(filters.draft.order_channel, 'cash')
  assert.deepEqual(filters.draft.dateRange, form.dateRange)
})

test('apply, tag removal and reset each query once and preserve the current tab', () => {
  const { form, filters, calls } = setup()
  filters.openAdvanced()
  filters.draft.order_channel = 'cash'
  filters.applyAdvanced()
  assert.equal(calls(), 1)
  assert.equal(filters.advancedVisible.value, false)
  assert.deepEqual(filters.advancedTags.value, [{ key: 'order_channel', label: '订单渠道：现金单' }])
  filters.removeAdvanced('order_channel')
  assert.equal(calls(), 2)
  assert.deepEqual(filters.advancedTags.value, [])
  filters.resetFilters()
  assert.equal(calls(), 3)
  assert.equal(form.order_kind, 'business')
  assert.equal(form.customer_name, '')
  assert.equal(form.keyword, '')
  assert.equal(form.status, '')
})

test('production queries exclude business conditions but keep customer and date queries', () => {
  const { form, filters } = setup()
  form.order_kind = 'production'
  form.customer_source = 'referral'
  filters.openAdvanced()
  filters.draft.order_channel = 'cash'
  filters.draft.dateRange = ['2026-09-01', '2026-09-11']
  filters.applyAdvanced()
  assert.equal(form.customer_source, '')
  assert.equal(form.order_channel, '')
  assert.equal(filters.advancedTags.value.length, 1)
  const params = buildOrderListParams({ ...form, order_type: 'first_order' })
  assert.equal(params.order_type, undefined)
  assert.equal(params.customer_name, '莱莎')
  assert.equal(params.date_end, '2026-09-11')
})
