import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'
import * as integration from '../src/views/system/integrationAppManagement.js'
import * as tokens from '../src/views/system/mcpTokenManagement.js'
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

for (const [file, resource, method, module, envelope] of [
  ['RoleManagement.vue', 'roleResource', 'getRoleList', 'userManagement', 'array'],
  ['IntegrationAppManagement.vue', 'appResource', 'listIntegrationApps', 'integrationApps', 'items'],
  ['McpTokenManagement.vue', 'tokenResource', 'listMcpTokens', 'mcpTokens', 'items'],
]) test(file + ' has first-failure retry and preserves rows on refresh failure', async t => {
  let fail = true
  const { vm } = viewController(t, '../../src/views/system/' + file, resource + ',reloadRows', {
    ['@/api/' + module]: { [method]: async config => {
      assert.ok(config.signal); assert.equal(config.suppressToast, true)
      if (fail) throw Error('offline')
      return { data: envelope === 'array' ? [{ id: 1 }] : { items: [{ id: 1 }] } }
    } },
    './composables/usePermissionMatrix': { usePermissionMatrix: () => ({}) },
    './integrationAppManagement': integration, './mcpTokenManagement': tokens,
  })
  await vm.reloadRows(); assert.equal(vm[resource].errorMessage.value, 'offline'); assert.equal(vm[resource].isEmpty.value, false)
  fail = false; await vm.reloadRows(); fail = true; await vm.reloadRows()
  assert.equal(vm[resource].data.value[0].id, 1); assert.equal(vm[resource].isStale.value, true)
})

test('dictionary type scope clears old rows and ignores a late former type response', async t => {
  const pending = deferred(); let fail = false
  const { vm } = viewController(t, '../../src/views/system/DictManagement.vue', 'itemsResource,typesResource,currentType,fetchItems,fetchTypes', {
    '@/api/system': {
      getDictTypes: async config => { assert.ok(config.signal); return { data: [{ type: 'one' }] } },
      getDictItems: async (type, active, config) => {
        assert.equal(active, false); assert.ok(config.signal)
        if (type === 'slow') return pending.promise
        if (fail) throw Error('type unavailable')
        return { data: [{ type }] }
      },
    },
  })
  await vm.fetchTypes(); assert.equal(vm.itemsResource.data.value[0].type, 'one')
  vm.currentType.value = 'slow'; const old = vm.fetchItems(); assert.equal(vm.itemsResource.data.value.length, 0)
  vm.currentType.value = 'next'; fail = true; await vm.fetchItems()
  assert.equal(vm.itemsResource.data.value.length, 0)
  pending.resolve({ data: [{ type: 'slow' }] }); await old
  assert.equal(vm.itemsResource.data.value.length, 0); assert.equal(vm.itemsResource.errorMessage.value, 'type unavailable')
})

test('binding candidate refresh preserves applied status, including an empty reset', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/system/ExternalBindings.vue', 'listState,statusFilter,handleSearch,loadCandidates,resetFilters', {
    '@/api/clients': { adminClient: { get: async (_, config) => { calls.push(config.params); assert.ok(config.signal); return { data: [{ id: 1 }] } } } },
  })
  vm.statusFilter.value = 'bound'; await vm.handleSearch(); vm.statusFilter.value = 'pending'; await vm.loadCandidates()
  assert.equal(calls.at(-1).status, 'bound'); await vm.resetFilters(); assert.deepEqual(calls.at(-1), {})
})

test('credential local filters apply only on query; successful issue keeps its one-time secret after read failure', async t => {
  let writes = 0
  const { vm } = viewController(t, '../../src/views/system/IntegrationAppManagement.vue', 'appResource,filters,appliedFilters,hasPendingSearch,searchRows,resetFilters,submitCreate,createForm,candidates,issuedSecret,secretVisible', {
    './integrationAppManagement': integration, './mcpTokenManagement': tokens,
    '@/api/integrationApps': {
      listIntegrationApps: async () => { throw Error('refresh unavailable') },
      createIntegrationApp: async () => { writes++; return { data: { token: 'fixture-only', name: 'example' } } },
    },
  })
  vm.filters.keyword = 'draft'; assert.equal(vm.hasPendingSearch.value, true); assert.equal(vm.appliedFilters.value.keyword, '')
  vm.searchRows(); assert.equal(vm.appliedFilters.value.keyword, 'draft'); vm.resetFilters(); assert.equal(vm.appliedFilters.value.keyword, '')
  vm.createForm.name = 'example'; vm.createForm.ownerUserId = 7; vm.candidates.value = [{ user_id: 7, has_invoice_write: true }]
  await vm.submitCreate()
  assert.equal(writes, 1); assert.equal(vm.secretVisible.value, true); assert.equal(vm.issuedSecret.value.token, 'fixture-only')
  assert.equal(vm.appResource.errorMessage.value, 'refresh unavailable')
})

