import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as trackingStatus from '../src/views/tracking/trackingStatus.js'

const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
function products(t, api = {}) {
  return viewController(t, '../../src/views/production/ProductManage.vue', 'filterOptionsResource,filterOptions,loadFilterOptions,activeRoutesResource,activeRoutes,loadActiveRoutes,previewResource,previewSteps,loadPreview,bindDialogVisible,bindTarget,bindRouteId,openBindDialog,handleBind,batchBindVisible,batchRouteId,openBatchBind,handleBatchBind,selectedProducts,listState', {
    '@/api/production': {
      getProducts: async () => ({ items: [], total: 0 }),
      getRouteSteps: async id => ({ steps: [{ process_id: id }] }),
      getActiveRoutes: async () => [], getProductFilterOptions: async () => ({ models: [], group_names: [] }),
      ...api,
    },
  })
}
function tracking(t, api = {}) {
  return viewController(t, '../../src/views/tracking/TrackingList.vue', 'statsResource,stats,lastUpdated,fetchStats,listState,handleRefresh,getStatValue', {
    '@/api/tracking': { getShipmentList: async () => ({ data: { items: [], total: 0 } }), ...api },
    './trackingStatus.js': trackingStatus,
    './composables/useTrackingTableView': { useTrackingTableView: () => ({}) },
  })
}

test('product filter options and active routes have independent first errors, retry and retained results', async t => {
  let failOptions = true, failRoutes = true
  const { vm } = products(t, {
    getProductFilterOptions: async config => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (failOptions) throw Error('options offline'); return { models: ['M'], group_names: ['G'] } },
    getActiveRoutes: async config => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (failRoutes) throw Error('routes offline'); return [{ id: 1 }] },
  })
  await Promise.all([vm.loadFilterOptions(), vm.loadActiveRoutes()])
  assert.equal(vm.filterOptionsResource.errorMessage.value, 'options offline'); assert.equal(vm.activeRoutesResource.errorMessage.value, 'routes offline')
  failOptions = false; await vm.loadFilterOptions(); assert.deepEqual(vm.filterOptions.value.models, ['M']); assert.equal(vm.activeRoutesResource.hasLoaded.value, false)
  failRoutes = false; await vm.loadActiveRoutes(); failOptions = true; failRoutes = true
  await Promise.all([vm.loadFilterOptions(), vm.loadActiveRoutes()])
  assert.equal(vm.filterOptionsResource.isStale.value, true); assert.equal(vm.activeRoutesResource.isStale.value, true)
  assert.deepEqual(vm.filterOptions.value.models, ['M']); assert.equal(vm.activeRoutes.value[0].id, 1)
})

test('route preview clears on route change and ignores the former route response', async t => {
  const old = deferred(); let oldSignal
  const { vm } = products(t, { getRouteSteps: async (id, config) => { assert.equal(config.suppressToast, true); if (id === 1) { oldSignal = config.signal; return old.promise }; return { steps: [{ process_id: 22 }] } } })
  vm.openBindDialog({ product_id: 1, process_route: { route_id: 1 } }); vm.bindRouteId.value = 2; await nextTick()
  old.resolve({ steps: [{ process_id: 11 }] }); await old.promise; await nextTick()
  assert.equal(oldSignal.aborted, true); assert.equal(vm.bindRouteId.value, 2); assert.equal(vm.previewSteps.value[0].process_id, 22)
})

test('preview first read error is visible, retry works, same route failure keeps steps, new failed route clears old', async t => {
  let fail = true
  const { vm } = products(t, { getRouteSteps: async id => { if (fail) throw Error('preview offline'); return { steps: [{ process_id: id }] } } })
  vm.openBindDialog({ product_id: 1, process_route: { route_id: 1 } }); await new Promise(resolve => setImmediate(resolve))
  assert.equal(vm.previewResource.errorMessage.value, 'preview offline'); assert.equal(vm.previewResource.isEmpty.value, false)
  fail = false; await vm.loadPreview(); fail = true; await vm.loadPreview()
  assert.equal(vm.previewResource.isStale.value, true); assert.equal(vm.previewSteps.value[0].process_id, 1)
  vm.bindRouteId.value = 2; await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(vm.previewSteps.value, []); assert.equal(vm.previewResource.hasLoaded.value, false)
  fail = false; await vm.loadPreview(); assert.equal(vm.previewSteps.value[0].process_id, 2)
})

test('closing preview or selecting unlink cancels and clears pending route detail', async t => {
  for (const close of [true, false]) {
    const old = deferred(); let signal
    const { vm } = products(t, { getRouteSteps: async (_, config) => { signal = config.signal; return old.promise } })
    vm.openBindDialog({ product_id: 1, process_route: { route_id: 1 } })
    if (close) vm.bindDialogVisible.value = false
    else vm.bindRouteId.value = null
    assert.equal(signal.aborted, true); old.resolve({ steps: [{ process_id: 1 }] }); await old.promise; await nextTick()
    assert.deepEqual(vm.previewSteps.value, []); assert.equal(vm.previewResource.hasLoaded.value, false)
  }
})

test('changing products with the same route ID starts a new preview scope', async t => {
  const old = deferred(); let reads = 0
  const { vm } = products(t, { getRouteSteps: async () => ++reads === 1 ? old.promise : { steps: [{ process_id: 22 }] } })
  vm.openBindDialog({ product_id: 1, process_route: { route_id: 7 } }); vm.openBindDialog({ product_id: 2, process_route: { route_id: 7 } }); await nextTick()
  old.resolve({ steps: [{ process_id: 11 }] }); await old.promise; await nextTick()
  assert.equal(reads, 2); assert.equal(vm.previewSteps.value[0].process_id, 22)
})

test('single binding captures product and route; late success does not close a new dialog', async t => {
  const write = deferred(), writes = []
  const { vm, messages } = products(t, { bindProductRoute: async (id, payload) => { writes.push({ id, payload }); return write.promise } })
  vm.openBindDialog({ product_id: 1, process_route: { route_id: 7 } }); const pending = vm.handleBind()
  vm.openBindDialog({ product_id: 2, process_route: { route_id: 8 } }); write.resolve(); await pending
  assert.deepEqual(writes, [{ id: 1, payload: { route_id: 7 } }]); assert.equal(vm.bindDialogVisible.value, true); assert.equal(vm.bindTarget.value.product_id, 2)
  assert.ok(messages.includes('绑定成功'))
})

test('binding success and null unlink payload survive subsequent main-list read error', async t => {
  const writes = []
  const { vm, messages } = products(t, { bindProductRoute: async (id, payload) => writes.push({ id, payload }), getProducts: async () => { throw Error('saved list offline') } })
  vm.openBindDialog({ product_id: 1 }); await vm.handleBind()
  assert.deepEqual(writes, [{ id: 1, payload: { route_id: null } }]); assert.equal(vm.bindDialogVisible.value, false)
  assert.ok(messages.includes('绑定成功')); assert.equal(vm.listState.errorMessage.value, 'saved list offline')
})

test('batch binding captures product IDs and route while leaving a new selection/dialog intact', async t => {
  const write = deferred(), writes = []
  const { vm, messages } = products(t, { batchBindRoute: async payload => { writes.push(payload); return write.promise } })
  vm.selectedProducts.value = [{ product_id: 1 }, { product_id: 2 }]; vm.openBatchBind(); vm.batchRouteId.value = 7
  const pending = vm.handleBatchBind(); vm.openBatchBind(); vm.selectedProducts.value = [{ product_id: 3 }]; vm.batchRouteId.value = 8
  write.resolve({ message: 'saved' }); await pending
  assert.deepEqual(writes, [{ product_ids: [1, 2], route_id: 7 }]); assert.equal(vm.batchBindVisible.value, true); assert.equal(vm.batchRouteId.value, 8)
  assert.ok(messages.includes('saved'))
})

test('tracking summary exposes first error independently and retains stats and timestamp after refresh failure', async t => {
  let fail = true
  const { vm } = tracking(t, { getTrackingStats: async (params, config) => { assert.equal(params, undefined); assert.ok(config.signal); assert.equal(config.suppressToast, true); if (fail) throw Error('stats offline'); return { data: { total: 10, delivered: 4 } } } })
  await vm.listState.fetchList(); await vm.fetchStats(); assert.equal(vm.stats.value, null); assert.equal(vm.statsResource.errorMessage.value, 'stats offline')
  assert.equal(vm.listState.errorMessage.value, ''); fail = false; await vm.fetchStats(); const timestamp = vm.lastUpdated.value
  fail = true; await vm.fetchStats(); assert.equal(vm.stats.value.total, 10); assert.equal(vm.lastUpdated.value, timestamp); assert.equal(vm.statsResource.isStale.value, true)
  fail = false; await vm.fetchStats(); assert.equal(vm.statsResource.errorMessage.value, '')
})

test('late tracking summary cannot override newer totals or completion time', async t => {
  const old = deferred(); let reads = 0
  const { vm } = tracking(t, { getTrackingStats: async () => ++reads === 1 ? old.promise : { data: { total: 20 } } })
  const pending = vm.fetchStats(); await vm.fetchStats(); const timestamp = vm.lastUpdated.value
  old.resolve({ data: { total: 10 } }); await pending
  assert.equal(vm.stats.value.total, 20); assert.equal(vm.lastUpdated.value, timestamp)
})

test('tracking permission/user scope change clears prior aggregates and excludes late reads', async t => {
  const old = deferred(); let reads = 0
  const { vm, auth } = tracking(t, { getTrackingStats: async () => ++reads === 2 ? old.promise : reads === 3 ? Promise.reject(Error('new scope offline')) : { data: { total: 10 } } })
  await vm.fetchStats(); const pending = vm.fetchStats(); auth.user.id = 8; await nextTick()
  old.resolve({ data: { total: 99 } }); await pending
  assert.equal(vm.stats.value, null); assert.equal(vm.lastUpdated.value, ''); assert.equal(vm.statsResource.errorMessage.value, 'new scope offline')
})

test('shipment write success remains successful when the independent summary refresh fails', async t => {
  const { vm, messages } = tracking(t, { refreshShipment: async () => {}, getTrackingStats: async () => { throw Error('stats offline') } })
  await vm.handleRefresh({ waybill_no: 'WB1' }); await nextTick()
  assert.ok(messages.includes('刷新完成')); assert.equal(vm.statsResource.errorMessage.value, 'stats offline')
})

for (const [name, path] of [['getActiveRoutes', '/active-routes'], ['getProductFilterOptions', '/products/filter-options']]) {
  test(`${name} actual API forwards signal and silent read options`, async () => {
    const source = readFileSync(new URL('../src/api/production.js', import.meta.url), 'utf8')
    const declaration = source.split('\n').find(line => line.startsWith(`export const ${name} =`)).replace('export ', '')
    const signal = new AbortController().signal, calls = [], body = { id: 1 }
    const method = new Function('productionClient', declaration + `; return ${name};`)({ get: async (url, config) => { calls.push({ url, config }); return body } })
    assert.equal(await method({ signal, suppressToast: true }), body); assert.equal(calls[0].url, path)
    assert.equal(calls[0].config.signal, signal); assert.equal(calls[0].config.suppressToast, true); assert.equal(calls[0].config.showLoading, false)
  })
}

test('tracking stats actual API keeps caller params with request configuration', async () => {
  const source = readFileSync(new URL('../src/api/tracking.js', import.meta.url), 'utf8')
  const declaration = source.match(/export function getTrackingStats\([\s\S]*?\n}/)[0].replace('export ', '')
  const signal = new AbortController().signal, calls = [], params = { carrier: 'carrier1' }, body = { data: { total: 2 } }
  const method = new Function('request', declaration + ';return getTrackingStats;')({ get: async (path, config) => { calls.push({ path, config }); return body } })
  assert.equal(await method(params, { signal, suppressToast: true }), body); assert.deepEqual(calls[0].config.params, params)
  assert.equal(calls[0].config.signal, signal); assert.equal(calls[0].config.suppressToast, true); assert.equal(calls[0].config.showLoading, false)
})
