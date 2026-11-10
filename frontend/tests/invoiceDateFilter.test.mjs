import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'
import { createInvoiceSubmissionGuard } from '../src/views/invoice/composables/invoiceSubmissionGuard.js'
import { restoreTablePreferences } from '../src/utils/tableViewPreferences.js'

function harness(t, overrides = {}) {
  const calls = { list: [], summary: [] }
  const { vm } = viewController(t, '../../src/views/invoice/composables/useInvoiceManagePage.js', 'page: useInvoiceManagePage()', {
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, accessToken: 'fixture', roles: [], permissions: ['invoice:read'] }) },
    '@/utils/datetime': { currentBeijingDate: () => '2026-11-02' },
    './invoiceSubmissionGuard': { createInvoiceSubmissionGuard },
    '@/api/invoice': {
      listInvoices: async (params, options) => {
        calls.list.push(structuredClone(params))
        return overrides.listInvoices?.(params, options) ?? { items: [{ id: 1 }], total: 100 }
      },
      getInvoiceSummary: async params => { calls.summary.push(params); return { order_count: 1 } },
    },
  })
  return { page: vm.page, calls }
}

test('initial list and summary use the same complete Beijing calendar month', async t => {
  const { page, calls } = harness(t)
  await page.loadInvoices()
  assert.equal(calls.list[0].date_from, '2026-11-01')
  assert.equal(calls.list[0].date_to, '2026-11-30')
  assert.deepEqual(calls.summary[0], { date_from: '2026-11-01', date_to: '2026-11-30' })
})

test('invoice status filter offers cancellation in progress and omits archived states', t => {
  const { page } = harness(t)
  const statuses = page.statusOptions.map(({ value }) => value)
  assert.ok(statuses.includes('cancel_pending'))
  assert.ok(!statuses.includes('cancelled'))
  assert.ok(!statuses.includes('deleted'))
})

test('order amount appears before payable, survives saved preferences and sorts on the server', async t => {
  const { page, calls } = harness(t)
  const keys = page.columnDefs.map(column => column.key)
  assert.equal(keys.indexOf('order_amount') + 1, keys.indexOf('total_amount'))
  const oldKeys = keys.filter(key => key !== 'order_amount')
  const restored = restoreTablePreferences({ version: 1, knownColumnKeys: oldKeys, visibleKeys: oldKeys }, page.columnDefs)
  assert.ok(restored.visibleKeys.includes('order_amount'))
  await page.handlePageChange(3)
  await page.handleTableSort({ prop: 'order_amount', order: 'ascending' })
  assert.equal(calls.list.at(-1).page, 1)
  assert.equal(calls.list.at(-1).sort_field, 'order_amount')
  assert.equal(calls.list.at(-1).sort_order, 'asc')
})

test('date changes reset pagination, preserve applied filters and keep draft edits pending', async t => {
  const { page, calls } = harness(t)
  Object.assign(page.filters, { keyword: 'Customer', order_type: 'stock', status: 'ready', order_id: ' 123 ' })
  await page.handleSearch()
  await page.handleTableSort({ prop: 'invoice_no', order: 'ascending' })
  await page.handlePageChange(4)
  page.filters.keyword = 'not submitted'
  page.summaryDateRange.value = ['2026-09-01', '2026-09-30']
  await page.handleDateRangeChange()
  assert.deepEqual(calls.list.at(-1), {
    keyword: 'Customer', order_type: 'stock', status: 'ready', order_id: '123',
    date_from: '2026-09-01', date_to: '2026-09-30', page: 1, page_size: 20,
    sort_field: 'invoice_no', sort_order: 'asc',
  })
  assert.deepEqual(calls.summary.at(-1), { date_from: '2026-09-01', date_to: '2026-09-30' })
  assert.equal(page.hasPendingSearch.value, true)
  for (const action of [() => page.handlePageChange(2), () => page.handleSizeChange(50),
    () => page.handleSaved(), () => page.loadInvoices(), () => page.resetFilters()]) {
    await action()
    assert.equal(calls.list.at(-1).date_from, '2026-09-01')
    assert.equal(calls.list.at(-1).date_to, '2026-09-30')
  }
  assert.equal(calls.list.at(-1).keyword, '')
})

test('slow previous date response cannot replace the latest date rows or total', async t => {
  const requests = []
  const { page } = harness(t, { listInvoices: (_, { signal }) => new Promise(resolve => requests.push({ resolve, signal })) })
  const old = page.loadInvoices()
  page.summaryDateRange.value = ['2026-10-01', '2026-10-31']
  const latest = page.handleDateRangeChange()
  assert.equal(requests[0].signal.aborted, true)
  requests[1].resolve({ items: [{ id: 2 }], total: 1 })
  await latest
  requests[0].resolve({ items: [{ id: 1 }], total: 99 })
  await old
  assert.deepEqual(page.invoices.value, [{ id: 2 }])
  assert.equal(page.total.value, 1)
})
