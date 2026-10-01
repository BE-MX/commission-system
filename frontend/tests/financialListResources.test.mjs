import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useTableSort } from '../src/composables/useTableSort.js'
import { formatMoney } from '../src/utils/money.js'
import * as formats from '../src/views/commission/commissionFormat.js'
const settle = async () => { for (let i = 0; i < 6; i++) await Vue.nextTick() }
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

function financialView(t, path, names, api) {
  const scope = Vue.effectScope(), messages = []
  const route = Vue.reactive({ params: { batchId: 'one' } }), auth = Vue.reactive({ user: { id: 7 } })
  const modules = {
    vue: { ...Vue, onMounted() {} }, 'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) },
    '@/stores/auth': { useAuthStore: () => auth },
    '@/composables/useListPage': { useListPage }, '@/composables/useAsyncResource': { useAsyncResource },
    '@/composables/useTableSort': { useTableSort }, '@/composables/useTableView': { useTableView: () => ({}) },
    '@/utils/feedback': { msgSuccessText: text => messages.push(text), msgWarning: text => messages.push(text), confirmAction: async () => {} },
    '@/api/commission': api, '@/api/payment': api, '@/api/customer': api,
    './commissionFormat': formats,
  }
  const script = parse(readFileSync(new URL(path, import.meta.url), 'utf8')).descriptor.scriptSetup.content
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
      modules[key] ??= key.endsWith('/money.js') ? { formatMoney } : {}
      const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
      return `const ${declaration} = modules[${JSON.stringify(key)}];`
    })
  const vm = scope.run(() => new Function('modules', `${script}\nreturn { ${names} };`)(modules))
  t.after(() => scope.stop())
  return { vm, route, auth, messages }
}

test('batch query/sort/page use submitted conditions and successful creation remains successful after a read failure', async t => {
  const calls = []; let failed = false, writes = 0
  const { vm, messages } = financialView(t, '../src/views/commission/CommissionBatch.vue',
    'listState,statusFilter,handleSearch,changeSort,submitCreate,createForm,createDateRange', {
      getBatchList: async (params, config) => { calls.push({ ...params }); assert.ok(config.signal); if (failed) throw Error('offline'); return { data: { items: [{ id: 1 }], total: 100 } } },
      createBatch: async () => { writes++; failed = true },
    })
  vm.statusFilter.value = 'draft'; await vm.handleSearch()
  vm.statusFilter.value = 'confirmed'
  await vm.changeSort({ prop: 'created_at', order: 'descending' }); await vm.listState.handlePageChange(3)
  assert.equal(calls.at(-1).status, 'draft'); assert.equal(calls.at(-1).sort_order, 'desc')
  vm.createForm.value = { batch_name: 'test', period_type: 'quarterly' }; vm.createDateRange.value = ['2026-01-01', '2026-03-31']
  await vm.submitCreate(); await settle()
  assert.equal(writes, 1); assert.ok(messages.includes('批次创建成功'))
  assert.equal(vm.listState.errorMessage.value, 'offline'); assert.equal(vm.listState.dataPage.value, 3)
  assert.equal(calls.at(-1).page, 1); assert.equal(calls.at(-1).status, 'draft')
})

test('snapshot filters preserve the all/true/false boundary, draft fields and applied sort', async t => {
  const calls = []
  const { vm } = financialView(t, '../src/views/customer/CustomerSnapshot.vue',
    'listState,keyword,salespersonKeyword,isComplete,searchList,resetFilters,changeSort', {
      getSnapshotList: async params => { calls.push(params); return { data: { items: [], total: 0 } } },
    })
  vm.keyword.value = 'Alice'; vm.salespersonKeyword.value = '7'; vm.isComplete.value = 'false'
  await vm.searchList(); vm.keyword.value = 'draft'
  await vm.changeSort({ prop: 'first_receipt_date', order: 'ascending' })
  await vm.listState.handlePageChange(2)
  assert.equal(calls.at(-1).keyword, 'Alice'); assert.equal(calls.at(-1).is_complete, 'false')
  assert.equal(calls.at(-1).salesperson_keyword, '7')
  await vm.resetFilters(); assert.equal(calls.at(-1).is_complete, 'all'); assert.equal(calls.at(-1).keyword, '')
})

test('payment pagination preserves submitted dates and reset preserves the synchronization context', async t => {
  const calls = []
  const { vm } = financialView(t, '../src/views/payment/PaymentSync.vue', 'listState,dateRange,listKeyword,searchPayments,resetListFilter,formatExchangeRate', {
    getSyncedPayments: async params => { calls.push(params); return { data: { items: [], total: 0 } } },
  })
  vm.dateRange.value = ['2026-01-01', '2026-01-31']; vm.listKeyword.value = 'paid'; await vm.searchPayments()
  vm.dateRange.value[0] = '2026-02-01'; vm.listKeyword.value = 'draft'
  await vm.listState.handlePageChange(2)
  assert.equal(calls.at(-1).date_start, '2026-01-01'); assert.equal(calls.at(-1).date_end, '2026-01-31'); assert.equal(calls.at(-1).keyword, 'paid')
  await vm.resetListFilter(); assert.equal(calls.at(-1).date_start, '2026-02-01'); assert.equal(calls.at(-1).keyword, '')
  assert.equal(vm.formatExchangeRate(7.12345), '7.1235')
})

test('self commission stale responses cannot overwrite selected batch and switching identity clears prior financial rows', async t => {
  const late = deferred(); let requests = 0, fail = false
  const { vm, auth } = financialView(t, '../src/views/commission/SalesCommission.vue', 'listState,selectedBatch,fetchList', {
    getMyCommissionBatches: async () => {
      requests++
      if (requests === 2) return late.promise
      if (fail) throw Error('new identity offline')
      return { data: { items: [{ id: requests, batch_name: `batch${requests}` }], total: 1 } }
    },
  })
  await settle(); const old = vm.fetchList(); await vm.fetchList()
  late.resolve({ data: { items: [{ id: 999 }], total: 1 } }); await old
  assert.equal(vm.selectedBatch.value.id, 3)
  fail = true; auth.user.id = 8
  assert.deepEqual(vm.listState.list.value, []); assert.equal(vm.selectedBatch.value, null)
  await settle(); assert.equal(vm.listState.errorMessage.value, 'new identity offline')
})

test('batch scope changes invalidate old detail and summary responses together', async t => {
  const oldSummary = deferred(), oldList = deferred()
  const { vm, route } = financialView(t, '../src/views/commission/CommissionDetail.vue', 'listState,summaryState', {
    getBatchSummary: id => id === 'one' ? oldSummary.promise : Promise.resolve({ data: { batch_name: 'two' } }),
    getBatchDetails: id => id === 'one' ? oldList.promise : Promise.resolve({ data: { items: [{ batch_id: 'two' }], total: 1 } }),
  })
  route.params.batchId = 'two'; await settle()
  oldSummary.resolve({ data: { batch_name: 'old' } }); oldList.resolve({ data: { items: [{ batch_id: 'old' }], total: 1 } }); await settle()
  assert.equal(vm.summaryState.data.value.batch_name, 'two'); assert.equal(vm.listState.list.value[0].batch_id, 'two')
})
