import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as trackingStatus from '../src/views/tracking/trackingStatus.js'
import * as status from '../src/utils/status.js'

const resources = [
  ['production/ProcessManage.vue', 'production', 'getProcesses', false, 'searchName', 'search', 'resetFilters', 'name'],
  ['production/ProductManage.vue', 'production', 'getProducts', false, 'keyword', 'search', 'resetFilters', 'keyword'],
  ['employee/EmployeeAttribute.vue', 'employee', 'getEmployeeList', true, 'keyword', 'searchList', 'resetFilter', 'keyword'],
  ['supervisor/SupervisorRelation.vue', 'supervisor', 'getSupervisorList', true, 'keyword', 'search', 'resetFilters', 'keyword'],
  ['system/UserManagement.vue', 'userManagement', 'getUserList', true, 'keyword', 'searchList', 'resetFilters', 'keyword'],
  ['tracking/TrackingList.vue', 'tracking', 'getShipmentList', true, 'keyword', 'searchList', 'resetFilters', 'keyword'],
]
for (const [file, apiModule, method, envelope, draft, search, reset, param] of resources) {
  test(file + ' uses real shared state for failure, retry, draft isolation and current response', async t => {
    const calls = []; let fail = true, resolver
    const api = { [method]: async (params, config) => {
      calls.push(params); assert.ok(config.signal); assert.equal(config.suppressToast, true)
      if (params[param] === 'slow') return new Promise(resolve => { resolver = resolve })
      if (fail) throw Error('unavailable')
      const data = { items: [{ id: 1, name: 'retained' }], total: 100 }
      return envelope ? { data } : data
    } }
    const { vm } = viewController(t, '../../src/views/' + file, 'listState,' + draft + ',' + search + ',' + reset, {
      ['@/api/' + apiModule]: api,
      './trackingStatus.js': trackingStatus,
      './composables/useTrackingTableView': { useTrackingTableView: () => ({}) },
    })
    await vm.listState.fetchList(); assert.equal(vm.listState.errorMessage.value, 'unavailable'); assert.equal(vm.listState.isEmpty.value, false)
    fail = false; await vm.listState.fetchList()
    vm[draft].value = 'submitted'; await vm[search](); vm[draft].value = 'draft'
    await vm.listState.handlePageChange(3); await vm.listState.handleSortChange({ sort_field: 'id', sort_order: 'asc' })
    assert.equal(calls.at(-1)[param], 'submitted'); assert.equal(calls.at(-1).page, 1)
    fail = true; await vm.listState.fetchList(); assert.equal(vm.listState.list.value[0].name, 'retained'); assert.equal(vm.listState.isStale.value, true)
    fail = false; vm[draft].value = 'slow'; const old = vm[search](); vm[draft].value = 'new'; await vm[search]()
    resolver(envelope ? { data: { items: [{ name: 'old' }], total: 1 } } : { items: [{ name: 'old' }], total: 1 }); await old
    assert.equal(vm.listState.list.value[0].name, 'retained')
    await vm[reset](); assert.equal(calls.at(-1)[param] || '', '')
  })
}

test('disabled process status zero stays a submitted filter through page changes', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/production/ProcessManage.vue', 'listState,filterStatus,search', {
    '@/api/production': { getProcesses: async params => { calls.push(params); return { items: [], total: 0 } } },
  })
  vm.filterStatus.value = 0; await vm.search(); vm.filterStatus.value = 1
  await vm.listState.handlePageChange(2); assert.equal(calls.at(-1).status, 0)
})

test('process create and delete follow server ordering and recover an invalid last page', async t => {
  const calls = []; let total = 21, readsFail = false
  const { vm, messages } = viewController(t, '../../src/views/production/ProcessManage.vue', 'listState,form,formRef,handleSubmit,handleDelete', {
    '@/api/production': {
      getProcesses: async params => { calls.push(params); if (readsFail) throw Error('read failed'); return { items: params.page === 2 ? [] : [{ id: 1 }], total } },
      createProcess: async () => { readsFail = true }, deleteProcess: async () => { total = 20 },
    },
  })
  vm.formRef.value = { validate: async () => true }; vm.form.value = { name: 'new' }; vm.listState.page.value = 3
  await vm.handleSubmit(); assert.equal(calls.at(-1).page, 1); assert.ok(messages.includes('已创建')); assert.equal(vm.listState.errorMessage.value, 'read failed')
  readsFail = false; vm.listState.page.value = 2; await vm.handleDelete({ id: 1 }); await nextTick()
  assert.equal(vm.listState.page.value, 1); assert.equal(calls.at(-1).page, 1)
})

test('tracking kanban explicitly applies status and resetting clears only its UI highlight', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/tracking/TrackingList.vue', 'listState,handleKanbanClick,resetFilters,activeKanban,statusFilter', {
    '@/api/tracking': { getShipmentList: async params => { calls.push(params); return { data: { items: [], total: 0 } } } },
    './trackingStatus.js': trackingStatus, './composables/useTrackingTableView': { useTrackingTableView: () => ({}) },
    '@/utils/status': status,
  })
  await vm.handleKanbanClick({ key: 'delivered', statusValue: 'delivered' }); assert.equal(calls.at(-1).status, 'delivered')
  vm.statusFilter.value = 'exception'; await vm.listState.handlePageChange(2); assert.equal(calls.at(-1).status, 'delivered')
  await vm.resetFilters(); assert.equal(calls.at(-1).status, ''); assert.equal(vm.activeKanban.value, '')
})

