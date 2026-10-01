import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'
import * as conditionalRouting from '../src/views/domestic/conditionalRouting.js'
import { saveRouteConfiguration } from '../src/views/production/routeSaveFlow.js'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function routeController(t, api = {}, domestic = {}, permissions = ['production:admin', 'domestic:admin'], leave = async () => true) {
  const writes = [], reads = []
  const production = {
    getProcessRoutes: async () => ({ items: [{ id: 1 }, { id: 2 }] }),
    getActiveProcesses: async config => { reads.push(config); return [{ id: 11, name: 'A' }] },
    getRouteSteps: async (id, config) => { reads.push(config); return { steps: [{ process_id: id * 11, process_name: `route ${id}` }] } },
    saveRouteSteps: async (id, steps) => writes.push({ id, steps }),
    ...api,
  }
  const rules = {
    getDomesticRouteRules: async (id, config) => { reads.push(config); return { data: [] } },
    saveDomesticRouteConfiguration: async (id, steps, rules) => writes.push({ id, steps, rules }),
    saveDomesticRouteRules: async (id, rules) => writes.push({ id, rules }),
    ...domestic,
  }
  const { vm, messages } = viewController(t, '../../src/views/production/ProcessRouteManage.vue',
    'selectRoute,doSelectRoute,selectedRoute,editableSteps,stepsDirty,rulesDirty,loadingRoute,detailResource,processesResource,editorReady,routeRulesLoaded,ruleSaveError,fetchSelectedRoute,loadAllProcesses,allProcesses,saveSteps,saveRules,confirmAddStep,selectedNewSteps,applyConfirmedTemplate', {
      '@/api/production': production, '@/api/domestic': rules,
      '@/stores/auth': { useAuthStore: () => ({ hasPermission: permission => permissions.includes(permission) }) },
      '@/views/domestic/conditionalRouting': conditionalRouting,
      './routeSaveFlow': { saveRouteConfiguration }, './useRouteDraftGuard': { useRouteDraftGuard: () => leave },
    })
  return { vm, writes, reads, messages }
}

test('late route detail cannot replace the selected route or its editor', async t => {
  const old = deferred()
  const { vm } = routeController(t, { getRouteSteps: async id => id === 1 ? old.promise : { steps: [{ process_id: 22 }] } })
  const pending = vm.doSelectRoute({ id: 1 }); await vm.doSelectRoute({ id: 2 })
  old.resolve({ steps: [{ process_id: 11 }] }); await pending
  assert.equal(vm.selectedRoute.value.id, 2); assert.equal(vm.editableSteps.value[0].process_id, 22)
})

test('failed new route clears former steps, exposes retry and blocks all saves', async t => {
  let fail = false
  const { vm, writes } = routeController(t, { getRouteSteps: async id => { if (fail) throw Error('steps offline'); return { steps: [{ process_id: id * 11 }] } } })
  await vm.doSelectRoute({ id: 1 }); fail = true; assert.equal(await vm.doSelectRoute({ id: 2 }), false)
  assert.deepEqual(vm.editableSteps.value, []); assert.equal(vm.detailResource.errorMessage.value, 'steps offline')
  assert.equal(vm.editorReady.value, false); vm.stepsDirty.value = true; vm.rulesDirty.value = true
  await vm.saveSteps(); await vm.saveRules(); assert.deepEqual(writes, [])
  vm.stepsDirty.value = false; vm.rulesDirty.value = false; fail = false
  assert.equal(await vm.fetchSelectedRoute(), true); assert.equal(vm.editableSteps.value[0].process_id, 22)
})

test('same route read failure preserves dirty editor; successful retry does not discard its draft', async t => {
  let fail = false
  const { vm } = routeController(t, { getRouteSteps: async () => { if (fail) throw Error('detail refresh offline'); return { steps: [{ process_id: 11 }] } } })
  await vm.doSelectRoute({ id: 1 }); vm.editableSteps.value.push({ process_id: 99, rule_type: 'required', options: [] }); vm.stepsDirty.value = true
  fail = true; await vm.fetchSelectedRoute()
  assert.equal(vm.detailResource.isStale.value, true); assert.equal(vm.editableSteps.value[1].process_id, 99); assert.equal(vm.stepsDirty.value, true)
  fail = false; await vm.fetchSelectedRoute(); assert.equal(vm.editableSteps.value[1].process_id, 99); assert.equal(vm.stepsDirty.value, true)
})

test('rule network failure is visible and blocks combined writes; only forbidden non-rule editor may degrade', async t => {
  const offline = routeController(t, {}, { getDomesticRouteRules: async () => { throw Error('rules offline') } })
  await offline.vm.doSelectRoute({ id: 1 }); assert.equal(offline.vm.detailResource.errorMessage.value, 'rules offline')
  offline.vm.stepsDirty.value = true; await offline.vm.saveSteps(); assert.deepEqual(offline.writes, [])
  const forbidden = Object.assign(Error('not permitted'), { response: { status: 403 } })
  const viewer = routeController(t, {}, { getDomesticRouteRules: async () => { throw forbidden } }, ['production:admin'])
  assert.equal(await viewer.vm.doSelectRoute({ id: 1 }), true); assert.equal(viewer.vm.routeRulesLoaded.value, false)
  viewer.vm.stepsDirty.value = true; await viewer.vm.saveSteps(); assert.equal(viewer.writes[0].id, 1)
})

test('active processes have independent retry, stale preservation and signal options', async t => {
  let fail = true
  const { vm, reads } = routeController(t, { getActiveProcesses: async config => { reads.push(config); if (fail) throw Error('processes offline'); return [{ id: 11 }] } })
  assert.equal(await vm.loadAllProcesses(), false); assert.equal(vm.processesResource.hasLoaded.value, false)
  await vm.doSelectRoute({ id: 1 }); assert.equal(vm.editorReady.value, true)
  fail = false; await vm.loadAllProcesses(); fail = true; await vm.loadAllProcesses()
  assert.equal(vm.allProcesses.value[0].id, 11); assert.equal(vm.processesResource.isStale.value, true)
  vm.selectedNewSteps.value = [11]; vm.confirmAddStep(); assert.equal(vm.editableSteps.value.length, 1)
  for (const config of reads) { assert.ok(config.signal); assert.equal(config.suppressToast, true) }
})

test('successful configuration save remains successful if reload fails', async t => {
  let fail = false
  const { vm, messages } = routeController(t, { getRouteSteps: async () => { if (fail) throw Error('saved detail offline'); return { steps: [{ process_id: 11 }] } } },
    { saveDomesticRouteConfiguration: async () => { fail = true } })
  await vm.doSelectRoute({ id: 1 }); vm.stepsDirty.value = true; await vm.saveSteps()
  assert.ok(messages.includes('路线配置已保存')); assert.equal(vm.ruleSaveError.value, '')
  assert.equal(vm.detailResource.errorMessage.value, 'saved detail offline'); assert.equal(vm.stepsDirty.value, false)
})

test('late successful save refreshes only its original route and preserves the new route draft', async t => {
  const write = deferred()
  const { vm } = routeController(t, {}, { saveDomesticRouteConfiguration: async () => write.promise })
  await vm.doSelectRoute({ id: 1 }); vm.stepsDirty.value = true; const pending = vm.saveSteps()
  await vm.doSelectRoute({ id: 2 }); vm.editableSteps.value.push({ process_id: 99, rule_type: 'required', options: [] }); vm.stepsDirty.value = true
  write.resolve(); await pending
  assert.equal(vm.selectedRoute.value.id, 2); assert.equal(vm.editableSteps.value[1].process_id, 99); assert.equal(vm.stepsDirty.value, true)
})

test('route selection respects rejected dirty leave confirmation', async t => {
  const { vm } = routeController(t, {}, {}, undefined, async () => false)
  await vm.doSelectRoute({ id: 1 }); vm.stepsDirty.value = true; await vm.selectRoute({ id: 2 })
  assert.equal(vm.selectedRoute.value.id, 1); assert.equal(vm.stepsDirty.value, true)
})

test('late failed configuration and rule saves do not mark another route as failed or dirty', async t => {
  for (const kind of ['configuration', 'rules']) {
    const write = deferred()
    const { vm } = routeController(t, {}, {
      saveDomesticRouteConfiguration: async () => write.promise,
      saveDomesticRouteRules: async () => write.promise,
    })
    await vm.doSelectRoute({ id: 1 })
    if (kind === 'configuration') vm.stepsDirty.value = true
    else vm.rulesDirty.value = true
    const pending = kind === 'configuration' ? vm.saveSteps() : vm.saveRules()
    await vm.doSelectRoute({ id: 2 }); write.reject(Error('old route save failed')); await pending
    assert.equal(vm.selectedRoute.value.id, 2); assert.equal(vm.ruleSaveError.value, '')
    assert.equal(vm.rulesDirty.value, false); assert.equal(vm.stepsDirty.value, false)
  }
})

test('late save does not reload a newly selected editor even after returning to the same route ID', async t => {
  const write = deferred()
  const { vm } = routeController(t, {}, { saveDomesticRouteConfiguration: async () => write.promise })
  await vm.doSelectRoute({ id: 1 }); vm.stepsDirty.value = true; const pending = vm.saveSteps()
  await vm.doSelectRoute({ id: 2 }); await vm.doSelectRoute({ id: 1 })
  vm.editableSteps.value.push({ process_id: 99, rule_type: 'required', options: [] }); vm.stepsDirty.value = true
  write.resolve(); await pending
  assert.equal(vm.editableSteps.value[1].process_id, 99); assert.equal(vm.stepsDirty.value, true)
})
