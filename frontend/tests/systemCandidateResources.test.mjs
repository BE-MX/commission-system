import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as integration from '../src/views/system/integrationAppManagement.js'
import * as mcp from '../src/views/system/mcpTokenManagement.js'
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

for (const [view, method, visible, open, domain] of [
  ['IntegrationAppManagement', 'searchIntegrationAppCandidates', 'createVisible', 'openCreateDialog', '@/api/integrationApps'],
  ['McpTokenManagement', 'searchMcpTokenCandidates', 'issueVisible', 'openIssueDialog', '@/api/mcpTokens'],
]) {
  test(`${view} candidates keep the latest query, retry errors and cancel closed dialogs`, async t => {
    const old = deferred(); let failed = false, oldSignal
    const { vm } = viewController(t, `../../src/views/system/${view}.vue`, `candidateResource,candidates,candidateQuery,searchCandidates,${visible},${open}`, {
      './integrationAppManagement': integration, './mcpTokenManagement': mcp,
      [domain]: { [method]: async (params, config) => {
        assert.equal(config.suppressToast, true)
        if (params.q === 'old') { oldSignal = config.signal; return old.promise }
        if (failed) throw Error('users offline')
        return { data: { items: [{ user_id: params.q || 'initial' }] } }
      } },
    })
    vm[open](); await nextTick(); const pending = vm.searchCandidates('old'); await vm.searchCandidates('new')
    failed = true; await vm.searchCandidates('new'); assert.equal(vm.candidateResource.isStale.value, true)
    assert.equal(vm.candidates.value[0].user_id, 'new'); failed = false; await vm.searchCandidates(vm.candidateQuery.value)
    vm[visible].value = false; assert.equal(oldSignal.aborted, true)
    old.resolve({ data: { items: [{ user_id: 'old' }] } }); await pending
    assert.deepEqual(vm.candidates.value, []); assert.equal(vm.candidateResource.hasLoaded.value, false)
  })
}

test('external binding user search preserves successful suggestions after failure and clears on close/query reset', async t => {
  const old = deferred(); let failed = false
  const { vm } = viewController(t, '../../src/views/system/ExternalBindings.vue', 'userResource,userOptions,searchUsers,openBindDialog,bindDialogVisible', {
    '@/api/clients': { adminClient: { get: async (path, config) => {
      assert.equal(config.suppressToast, true)
      if (config.params.keyword === 'old') return old.promise
      if (failed) throw Error('users offline')
      return { data: { items: [{ id: 2 }] } }
    } } },
  })
  vm.openBindDialog({ suggested_user_id: 1, suggested_user_name: 'suggested' })
  assert.equal(vm.userOptions.value[0].id, 1)
  const pending = vm.searchUsers('old'); await vm.searchUsers('new'); failed = true; await vm.searchUsers('new')
  assert.equal(vm.userOptions.value[0].id, 2); assert.equal(vm.userResource.isStale.value, true)
  await vm.searchUsers(''); assert.deepEqual(vm.userOptions.value, [])
  vm.bindDialogVisible.value = false; old.resolve({ data: { items: [{ id: 999 }] } }); await pending
  assert.deepEqual(vm.userOptions.value, [])
})
