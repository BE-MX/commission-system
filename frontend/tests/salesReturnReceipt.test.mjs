import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'

const local = { id: 'return:71', return_id: 5, source: 'sales_return', purpose: 'sales_return', sync_status: 'local_only', status: 'active', collect_status: null, amount: '-200.00', currency: 'USD', receipt_no: 'RF-71', detail_url: '/invoice/sales-returns?return_id=5' }
async function harness(returnRead = false) {
  const calls = [], navigations = [], route = vue.reactive({ query: {} })
  const api = Object.fromEntries(['listReceipts', 'getReceipt', 'retryReceipt', 'voidReceipt', 'reconcileReceipt', 'resolveReceipt'].map(name => [name, async (...args) => {
    calls.push({ name, args }); return name === 'listReceipts' ? { items: [local], total: 101 } : { id: 7, amount: '100.00', source: 'manual', sync_status: 'pending', status: 'active' }
  }]))
  const context = vm.createContext({ console, JSON, Number, String, Promise })
  const imports = {
    vue,
    'vue-router': { useRoute: () => route, useRouter: () => ({ push: async target => navigations.push(target) }) },
    '@/stores/auth': { useAuthStore: () => ({ hasPermission: permission => returnRead && permission === 'sales_return:read' }) },
    '../../utils/requestKey.js': { newRequestKey: () => 'synthetic-request-key' },
    '../../utils/money.js': { formatMoney: String },
    '@/utils/feedback': { confirmAction: async () => {}, promptAction: async () => ({ value: 'verified reason' }), msgSuccess() {}, msgError() {} },
    '@/utils/datetime': { currentBeijingDate: () => '2026-10-30' },
    '@/composables/useListPage': { useListPage },
    '@/api/receipt': api,
  }
  const module = new vm.SourceTextModule(fs.readFileSync(new URL('../src/views/receipt/useReceipts.js', import.meta.url), 'utf8'), { context })
  await module.link(name => {
    const exports = imports[name]; assert.ok(exports, name)
    return new vm.SyntheticModule(Object.keys(exports), function () { for (const [key, value] of Object.entries(exports)) this.setExport(key, value) }, { context })
  })
  await module.evaluate()
  const scope = vue.effectScope(), state = scope.run(() => module.namespace.useReceipts())
  return { state, calls, navigations, module: module.namespace, stop: () => scope.stop() }
}
async function run(read, fn) { const h = await harness(read); try { await fn(h) } finally { h.stop() } }

test('local return opens the dedicated return details for an authorized return reader without a receipt fetch', () => run(true, async h => {
  await h.state.showDetail({ ...local, detail_url: 'https://untrusted.invalid' })
  assert.equal(h.calls.some(call => call.name === 'getReceipt'), false)
  assert.equal(h.navigations.length, 1)
  assert.equal(h.navigations[0].path, '/invoice/sales-returns')
  assert.equal(h.navigations[0].query.return_id, '5')
  assert.equal(h.state.detailVisible.value, false)
}))
test('receipt-only reader sees an authorized local summary and receives no failing navigation or ordinary detail request', () => run(false, async h => {
  await h.state.showDetail(local)
  assert.equal(h.calls.length, 0)
  assert.equal(h.navigations.length, 0)
  assert.equal(h.state.detailVisible.value, true)
  assert.equal(h.state.detail.value.amount, '-200.00')
  assert.equal(h.state.editable.value, false)
  assert.equal(h.module.statusLabel('local_only'), '仅方舟记账')
  assert.equal(h.module.sourceLabel('sales_return'), '退货退款')
}))
test('local return receipts never enter ordinary edit/void/retry/reconcile/resolve actions, including a source mismatch', () => run(false, async h => {
  h.state.detail.value = { ...local, source: 'manual', sync_status: 'failed' }
  assert.equal(h.state.editable.value, false)
  h.state.editCurrent()
  await h.state.retry(h.state.detail.value)
  await h.state.voidCurrent()
  await h.state.reconcile()
  await h.state.resolve('bind_receipt')
  assert.equal(h.calls.length, 0)
  assert.equal(h.state.editorVisible.value, false)
}))
test('ordinary receipt detail still uses the ordinary API and preserves editable behavior', () => run(false, async h => {
  await h.state.showDetail({ id: 7, source: 'manual' })
  assert.equal(h.calls[0].name, 'getReceipt')
  assert.equal(h.calls[0].args[0], 7)
  assert.equal(h.navigations.length, 0)
  assert.equal(h.state.editable.value, true)
}))
test('return source and sorting are sent to unified server paging; client uses server total and rows once', () => run(false, async h => {
  h.state.searchForm.source = 'sales_return'
  await h.state.handleSearch()
  await h.state.handleSortChange({ sort_field: 'amount', sort_order: 'asc' })
  await h.state.handlePageChange(3)
  const last = h.calls.at(-1).args[0]
  assert.equal(last.source, 'sales_return')
  assert.equal(last.sort_field, 'amount')
  assert.equal(last.sort_order, 'asc')
  assert.equal(last.page, 3)
  assert.equal(h.state.total.value, 101)
  assert.equal(h.state.list.value.length, 1)
  assert.equal(h.state.list.value[0].id, 'return:71')
}))

test('order fact keys distinguish sale, return and reversal rows of the same order in all metric detail tables', () => {
  const rows = [{ order_id: 'order-1' }, { order_id: 'order-1', fact_key: 'sales_return:5:activate' }, { order_id: 'order-1', fact_key: 'sales_return:5:reverse' }]
  for (const file of ['../src/views/perf-goal/components/MetricOrderTabs.vue', '../src/views/battle-report/components/ReportMetricOrders.vue', '../src/views/battle-report/components/ReportDaily.vue']) {
    const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8')
    const expression = source.match(/:key="(o\.fact_key \|\| o\.order_id)"/)?.[1]
    const arrow = source.match(/:row-key="(row => row\.fact_key \|\| row\.order_id)"/)?.[1]
    const key = expression ? new Function('o', `return ${expression}`) : new Function(`return (${arrow})`)()
    assert.equal(new Set(rows.map(key)).size, 3, file)
  }
})
