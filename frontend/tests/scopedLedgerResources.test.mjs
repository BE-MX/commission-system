import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, nextTick } from 'vue'
import { watchListResourceScope } from '../src/composables/useListResourceScope.js'
import { clearListResource } from '../src/composables/useListResourceScope.js'
import { viewController } from './helpers/viewController.mjs'
import * as workspaceController from '../src/views/customer_hub/customerWorkspaceController.js'
import * as membership from '../src/views/domestic/composables/domesticMemberPricing.js'
import * as battleHelpers from '../src/views/battle-report/helpers.js'
const scopeModule = { watchListResourceScope, clearListResource }

test('role permission selection ignores an earlier role load and a closed drawer', async t => {
  let release; const selection = []
  let call = 0
  const matrix = reactive({ allPerms: [], initSelection: ids => { selection.splice(0, selection.length, ...ids) }, loadPermissions: async () => {
    if (++call === 1) await new Promise(resolve => { release = resolve })
    return true
  } })
  const { vm } = viewController(t, '../../src/views/system/RoleManagement.vue', 'openPermDrawer,drawerVisible,drawerRole', {
    './composables/usePermissionMatrix': { usePermissionMatrix: () => matrix }, '@/api/userManagement': {},
  })
  const old = vm.openPermDrawer({ id: 1, permission_ids: [11] })
  await vm.openPermDrawer({ id: 2, permission_ids: [22] }); release(); await old
  assert.equal(vm.drawerRole.value.id, 2); assert.deepEqual(selection, [22])
})

test('festival summary failure does not block order rows, and type/user changes preserve submitted keyword', async t => {
  const calls = []; let failSummary = true, failRows = false
  const { vm } = viewController(t, '../../src/views/invoice/composables/useFestivalOrderDetail.js', 'useFestivalOrderDetail', {
    '@/composables/useListResourceScope': scopeModule,
    '@/api/festivalOrder': {
      getFestivalOrderSummary: async () => { if (failSummary) throw Error('summary offline'); return { new_sign: { count: 1 }, users: [] } },
      listFestivalOrders: async (params, config) => { calls.push(params); assert.ok(config.signal); if (failRows) throw Error('rows offline'); return { items: [{ id: 1 }], total: 100 } },
    },
  })
  const state = vm.useFestivalOrderDetail(); await state.loadPage()
  assert.equal(state.orders.value.length, 1); assert.equal(state.summaryResource.errorMessage.value, 'summary offline')
  state.filters.keyword = 'applied'; await state.search(); state.filters.keyword = 'draft'; await state.changePage(2)
  assert.equal(calls.at(-1).keyword, 'applied')
  state.selectedUserId.value = 9; failRows = true; await state.changeScope()
  assert.equal(state.orders.value.length, 0); assert.equal(calls.at(-1).user_id, 9); assert.equal(calls.at(-1).keyword, 'applied')
  failRows = false; state.activeType.value = 'repurchase'; await state.changeType()
  assert.equal(calls.at(-1).type, 'repurchase'); assert.equal(calls.at(-1).page, 1)
})

test('store quota size converts to real offset/limit, scope protects rows and recharge emits success even when reads fail', async t => {
  const props = reactive({ modelValue: false, storeId: 1 }), calls = []; let fails = false, release
  const { vm, messages } = viewController(t, '../../src/views/expo/StoreQuotaDrawer.vue', 'recordsState,quotaResource,handleRecharge,rechargeForm', {
    '@props': props, '@/composables/useListResourceScope': scopeModule, '@/api/expo': {
      getStoreQuota: async () => { if (fails) throw Error('quota failed'); return { data: { remaining: 5 } } },
      listQuotaRecords: async (id, params, config) => { calls.push({ id, ...params }); assert.ok(config.signal); if (id === 2) return new Promise(resolve => { release = resolve }); if (fails) throw Error('ledger failed'); return { data: { items: [{ id }], total: 200 } } },
      rechargeQuota: async () => { fails = true },
    },
  })
  props.modelValue = true; await nextTick(); await vm.recordsState.fetchList()
  await vm.recordsState.handleSizeChange(50); await vm.recordsState.handlePageChange(3)
  assert.equal(calls.at(-1).offset, 100); assert.equal(calls.at(-1).limit, 50)
  props.storeId = 2; await nextTick(); assert.equal(vm.recordsState.list.value.length, 0)
  props.storeId = 3; await nextTick(); await vm.recordsState.fetchList()
  release({ data: { items: [{ id: 2 }], total: 1 } }); await nextTick(); assert.equal(vm.recordsState.list.value[0].id, 3)
  await vm.handleRecharge(); assert.ok(messages.some(item => item.event === 'changed'))
  assert.equal(vm.recordsState.errorMessage.value, 'ledger failed'); assert.equal(vm.quotaResource.errorMessage.value, 'quota failed')
})

test('acquisition dialog preserves a successful page on retry failure and clears former job rows', async t => {
  let fail = false, release
  const { vm } = viewController(t, '../../src/views/customer_hub/AcquisitionTasks.vue', 'openResults,resultsState', {
    '@/composables/useListResourceScope': scopeModule,
    './composables/useCustomerHub': { useAcquisitionWorkflows: () => ({}) },
    './customerHubController': { createSearchJobDraft: () => ({}) },
    '@/api/customerHub': { listSearchJobResults: async (id, params) => { if (id === 1) return new Promise(resolve => { release = resolve }); if (fail) throw Error('results offline'); return { data: { items: [{ id }], total: 50 } } } },
  })
  const old = vm.openResults({ job_id: 1 }); await vm.openResults({ job_id: 2 }); release({ data: { items: [{ id: 1 }], total: 1 } }); await old
  assert.equal(vm.resultsState.list.value[0].id, 2)
  fail = true; await vm.resultsState.fetchList(); assert.equal(vm.resultsState.list.value[0].id, 2); assert.equal(vm.resultsState.isStale.value, true)
  await vm.openResults({ job_id: 3 }); assert.equal(vm.resultsState.list.value.length, 0)
})

test('workspace customer orders have real size/page and independent analysis and windows failures', async t => {
  const props = reactive({ customerId: 1 }), calls = []; let fail = false
  const { vm } = viewController(t, '../../src/views/customer_hub/workspace/WorkspaceOrders.vue', 'orderState,analyticsResource,windowsResource,handleSizeChange,handlePageChange', {
    '@props': props, '@/composables/useListResourceScope': scopeModule,
    '../customerWorkspaceController': workspaceController, '../workbenchV2Controller': { errorMessage: String },
    '@/api/customerHub': {
      listCustomerOrders: async (id, params, config) => { calls.push({ id, params }); assert.equal(config.suppressToast, true); if (fail) throw Error('orders offline'); return { data: { items: [{ id }], total: 201 } } },
      getOrderAnalytics: async () => { throw Error('analysis offline') }, getReorderWindows: async () => { throw Error('windows offline') },
    },
  })
  await vm.orderState.fetchList(); await vm.handleSizeChange(50); await vm.handlePageChange(3)
  assert.equal(calls.at(-1).params.page_size, 50); assert.equal(calls.at(-1).params.page, 3)
  assert.equal(vm.analyticsResource.errorMessage.value, 'analysis offline'); assert.equal(vm.windowsResource.errorMessage.value, 'windows offline')
  fail = true; await vm.orderState.fetchList(); assert.equal(vm.orderState.list.value[0].id, 1)
  props.customerId = 2; await nextTick(); await vm.orderState.fetchList(); assert.deepEqual(vm.orderState.list.value, [])
  assert.equal(calls.at(-1).id, 2)
})

test('domestic balance ledger snapshots its customer scope, retries stale pages and changes actual size', async t => {
  const calls = []; let fail = false, release
  const { vm } = viewController(t, '../../src/views/domestic/composables/useDomesticCustomers.js', 'useDomesticCustomers', {
    '@/composables/useListResourceScope': scopeModule, './domesticMemberPricing': membership,
    '@/api/domestic': { listCustomerBalanceLedger: async (id, params, config) => {
      calls.push({ id, params }); assert.equal(config.suppressToast, true)
      if (id === 1) return new Promise(resolve => { release = resolve })
      if (fail) throw Error('ledger offline'); return { data: { items: [{ id }], total: 201 } }
    } },
  })
  const state = vm.useDomesticCustomers(), old = state.openLedger({ id: 1 })
  await state.openLedger({ id: 2 }); release({ data: { items: [{ id: 1 }], total: 1 } }); await old
  assert.equal(state.ledgerDrawer.items[0].id, 2)
  await state.changeLedgerSize(50); await state.loadLedger(3)
  assert.equal(calls.at(-1).params.page_size, 50); assert.equal(calls.at(-1).params.page, 3)
  fail = true; await state.loadLedger(); assert.equal(state.ledgerState.isStale.value, true); assert.equal(state.ledgerDrawer.items[0].id, 2)
  await state.openLedger({ id: 3 }); assert.deepEqual(state.ledgerDrawer.items, [])
})

test('battle audit scope cancels on close and late former-report rows cannot repopulate it', async t => {
  let release; const calls = []
  const { vm } = viewController(t, '../../src/views/battle-report/BattleReports.vue', 'report,auditsVisible,auditState,changeAuditSize', {
    '@/composables/useListResourceScope': scopeModule, './helpers': battleHelpers,
    '@/api/battleReport': { battleReportApi: { audits: async (id, params, config) => {
      calls.push({ id, params }); assert.equal(config.suppressToast, true)
      if (id === 1) return new Promise(resolve => { release = resolve })
      return { items: [{ id }], total: 101 }
    } } },
  })
  vm.report.value = { id: 1 }; vm.auditsVisible.value = true
  vm.report.value = { id: 2 }; await vm.auditState.fetchList(); release({ items: [{ id: 1 }], total: 1 }); await Promise.resolve()
  assert.equal(vm.auditState.list.value[0].id, 2); await vm.changeAuditSize(50); assert.equal(calls.at(-1).params.page_size, 50)
  vm.auditsVisible.value = false; await vm.auditState.fetchList(); assert.deepEqual(vm.auditState.list.value, [])
  assert.equal(vm.auditState.appliedSearchForm.value.reportId, null)
})
