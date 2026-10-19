import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { computed, ref } from 'vue'
import { useListPage } from '../src/composables/useListPage.js'

function harness() {
  const script = fs.readFileSync(new URL('../src/views/battle-report/components/ReportMetricOrders.vue', import.meta.url), 'utf8')
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg, '')
  const calls = []
  const props = { report: { id: 7, members: [{ id: 2, team: 'A' }], detail_member_ids: [2] }, metric: 'combined', team: '' }
  const deps = { computed, ref, defineProps: () => props, useListPage, useTableMaxHeight: () => ({}),
    battleReportApi: { metricOrders: (id, params) => new Promise((resolve, reject) => calls.push({ id, params, resolve, reject })) } }
  return { ...new Function(...Object.keys(deps), `${script}\nreturn { state, meta };`)(...Object.values(deps)), calls }
}
const result = (name, amount) => ({ items: [{ order_name: name }], total: 42, total_amount: amount, customer_count: 5 })

test('pagination keeps applied filters and server full-result totals', async () => {
  const { state, meta, calls } = harness()
  Object.assign(state.searchForm, { customer: 'Alice', dates: ['2026-01-01', '2026-02-01'], order_name: 'Hair' })
  const first = state.handleSearch()
  assert.equal(calls[0].id, 7)
  assert.equal(calls[0].params.start_date, '2026-01-01')
  assert.equal(calls[0].params.metric, 'combined')
  calls[0].resolve(result('page 1', '999.99')); await first
  state.searchForm.customer = 'Unsubmitted'
  const next = state.handlePageChange(2)
  assert.equal(calls[1].params.customer, 'Alice')
  assert.equal(calls[1].params.page, 2)
  calls[1].resolve(result('page 2', '999.99')); await next
  assert.equal(meta.value.total_amount, '999.99')
  assert.equal(state.total.value, 42)
  const reset = state.handleReset()
  assert.equal(calls[2].params.customer, '')
  assert.equal(calls[2].params.start_date, undefined)
  assert.equal(calls[2].params.page, 1)
  calls[2].resolve(result('reset', '12.00')); await reset
})

test('stale responses cannot overwrite current rows or totals; cancellation prevents late summary writes', async () => {
  const { state, meta, calls } = harness()
  const old = state.handleSearch(), latest = state.handleSearch()
  calls[1].resolve(result('new', '20.00')); await latest
  calls[0].resolve(result('old', '900.00')); await old
  assert.equal(meta.value.total_amount, '20.00')
  assert.equal(state.list.value[0].order_name, 'new')
  const canceled = state.fetchList()
  state.cancel()
  calls[2].resolve(result('unmounted', '800.00')); await canceled
  assert.equal(meta.value.total_amount, '20.00')
})

test('failure exposes retry state and does not fabricate an empty successful result', async () => {
  const { state, calls } = harness()
  const request = state.fetchList()
  calls[0].reject(new Error('source unavailable'))
  assert.equal(await request, false)
  assert.match(state.errorMessage.value, /source unavailable/)
  assert.equal(state.isEmpty.value, false)
})
