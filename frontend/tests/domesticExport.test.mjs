import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const apiSource = readFileSync(new URL('../src/api/domestic.js', import.meta.url), 'utf8')
const viewSource = readFileSync(
  new URL('../src/views/domestic/DomesticOrders.vue', import.meta.url),
  'utf8',
)
const composableSource = readFileSync(
  new URL('../src/views/domestic/composables/useDomesticOrders.js', import.meta.url),
  'utf8',
)

test('domestic order export downloads one xlsx through the registered client', () => {
  const methodSource = apiSource.match(
    /export function exportOrder\(orderId\) \{[\s\S]*?\n\}/,
  )?.[0]
  assert.ok(methodSource, 'exportOrder API wrapper should exist')

  const calls = []
  const domesticClient = {
    get(path, config) {
      calls.push({ path, config })
      return 'response'
    },
  }
  const exportOrder = new Function(
    'domesticClient',
    `${methodSource.replace('export ', '')}; return exportOrder`,
  )(domesticClient)

  assert.equal(exportOrder(17), 'response')
  assert.deepEqual(calls, [{ path: '/orders/17/export', config: { responseType: 'blob' } }])
  assert.match(viewSource, /left-icon="Download" @click="handleExport\(row\)">导出<\/GlassButton>/)
  assert.match(composableSource, /downloadBlob\(response\)/)
})

const filtersSource = readFileSync(
  new URL('../src/views/domestic/composables/useDomesticOrderFilters.js', import.meta.url), 'utf8',
)
const { buildOrderExportParams } = new Function(
  `${filtersSource.replace(/^import .*$/m, '').replaceAll('export ', '')}; return { buildOrderExportParams }`,
)()

test('detail export preserves every filter including draft status, removes pagination and sort', () => {
  const form = {
    page: 3, page_size: 20, sort_field: 'order_date', sort_order: 'descending',
    keyword: ' 0001 ', customer_name: ' 店名 ', owner_user_id: 7, status: 0,
    order_kind: 'business', order_category: 'special', order_type: 'first_order',
    order_channel: 'wechat', customer_source: 'referral', dateRange: ['2026-09-01', '2026-09-30'],
  }
  assert.deepEqual(buildOrderExportParams(form), {
    keyword: '0001', customer_name: '店名', owner_user_id: 7, status: 0,
    order_kind: 'business', order_category: 'special', order_type: 'first_order',
    order_channel: 'wechat', customer_source: 'referral', date_start: '2026-09-01', date_end: '2026-09-30',
  })
  const production = buildOrderExportParams({ ...form, order_kind: 'production' })
  assert.equal(production.order_kind, 'production')
  assert.equal(production.order_category, undefined)
  assert.equal(production.customer_source, undefined)
})

test('detail export API uses the blob client and toolbar exposes loading and permission', () => {
  const method = apiSource.match(/export function exportOrderDetails\(params\) \{[\s\S]*?\n\}/)?.[0]
  assert.ok(method)
  const calls = []
  const api = new Function('domesticClient', `${method.replace('export ', '')}; return exportOrderDetails`)(
    { get: (...args) => calls.push(args) },
  )
  api({ status: 0 })
  assert.deepEqual(calls, [['/orders/export-details', { params: { status: 0 }, responseType: 'blob' }]])
  const button = viewSource.match(/<GlassButton[^>]*@click="handleExportDetails"[^>]*>导出订单明细<\/GlassButton>/)?.[0]
  assert.ok(button)
  assert.match(button, /v-any-permission/)
  assert.match(button, /:loading="exportingDetails"/)
  assert.match(button, /:disabled="loading \|\| exportingDetails \|\| !!listErrorMessage"/)
})

test('detail export uses applied filters, prevents double clicks and restores loading after failure', async () => {
  const method = composableSource.match(/  async function handleExportDetails\(\) \{[\s\S]*?\n  \}/)?.[0]
  assert.ok(method)
  const loading = { value: false }
  const form = { status: 0, owner_user_id: 9 }
  const listApi = { appliedSearchForm: { value: form }, searchForm: { status: 3 } }
  const requests = []
  const downloads = []
  let resolveRequest
  let failure = false
  const handler = new Function('exportingDetails', 'listApi', 'exportOrderDetails', 'buildOrderExportParams', 'downloadBlob',
    `${method}; return handleExportDetails`)(loading, listApi, params => {
    requests.push(params)
    return failure ? Promise.reject(new Error('download failed')) : new Promise(resolve => { resolveRequest = resolve })
  }, buildOrderExportParams, value => downloads.push(value))
  const first = handler()
  assert.equal(loading.value, true)
  await handler()
  assert.deepEqual(requests, [{ status: 0, owner_user_id: 9 }])
  resolveRequest('xlsx')
  await first
  assert.deepEqual(downloads, ['xlsx'])
  assert.equal(loading.value, false)
  failure = true
  await handler()
  assert.equal(loading.value, false)
  assert.deepEqual(downloads, ['xlsx'])
})
