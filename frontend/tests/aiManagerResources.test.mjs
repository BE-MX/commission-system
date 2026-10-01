import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'

for (const [stateName, method] of [['providerResource', 'getProviders'], ['presetResource', 'getPresets']]) {
  test('AI ' + stateName + ' retains complete rows after refresh failure', async t => {
    let fail = true, slow = false, release
    const { vm } = viewController(t, '../../src/views/system/composables/useAiManager.js', 'useAiManager', { '@/api/ai': {
      [method]: async (_, config) => {
        assert.ok(config.signal); assert.equal(config.suppressToast, true)
        if (slow) return new Promise(resolve => { release = resolve })
        if (fail) throw Error('offline')
        return { data: { items: [{ id: 2, name: 'current' }] } }
      },
    } })
    const state = vm.useAiManager()[stateName]
    await state.load(); assert.equal(state.errorMessage.value, 'offline'); assert.equal(state.isEmpty.value, false)
    fail = false; await state.load(); fail = true; await state.load()
    assert.equal(state.data.value[0].id, 2); assert.equal(state.isStale.value, true)
    fail = false; slow = true; const old = state.load(); slow = false; await state.load()
    release({ data: { items: [{ id: 1 }] } }); await old; assert.equal(state.data.value[0].id, 2)
  })
}

test('AI disabled provider filtering applies only on query and reset restores all rows', async t => {
  const { vm } = viewController(t, '../../src/views/system/composables/useAiManager.js', 'useAiManager', { '@/api/ai': {
    getProviders: async () => ({ data: { items: [{ id: 1, name: 'Enabled', api_base: 'x', is_enabled: true }, { id: 2, name: 'Disabled', api_base: 'x', is_enabled: false }] } }),
  } })
  const state = vm.useAiManager(); await state.fetchProviders(); state.providerStatusFilter.value = false
  assert.equal(state.filteredProviders.value.length, 2); state.searchProviders()
  assert.deepEqual(state.filteredProviders.value.map(p => p.id), [2])
  state.providerStatusFilter.value = true; await state.fetchProviders()
  assert.deepEqual(state.filteredProviders.value.map(p => p.id), [2])
  state.providerStatusFilter.value = undefined; state.searchProviders(); assert.equal(state.filteredProviders.value.length, 2)
  state.providerStatusFilter.value = null; state.searchProviders(); assert.equal(state.filteredProviders.value.length, 2)
  state.resetProviders(); assert.equal(state.filteredProviders.value.length, 2)
})

test('AI log summary only commits with the current query, and paging preserves submitted dates', async t => {
  const calls = []; let release, fail = false
  const { vm } = viewController(t, '../../src/views/system/composables/useAiManager.js', 'useAiManager', { '@/api/ai': {
    getLogs: async (params, config) => {
      calls.push(params); assert.ok(config.signal); assert.equal(config.suppressToast, true)
      if (params.status === 'slow') return new Promise(resolve => { release = resolve })
      if (fail) throw Error('logs failed')
      return { data: { items: [{ id: 2 }], total: 100, summary: { tokens_total: 200, success_count: 10, error_count: 0, timeout_count: 0, avg_duration_ms: 1 } } }
    },
  } })
  const state = vm.useAiManager(); state.logStatusFilter.value = 'error'; state.logDateRange.value = ['2026-09-01', '2026-09-30']; await state.searchLogs()
  state.logStatusFilter.value = 'draft'; state.logDateRange.value = ['2026-10-01', '2026-10-02']; await state.changeLogPage(3)
  assert.equal(calls.at(-1).status, 'error'); assert.equal(calls.at(-1).date_from, '2026-09-01')
  fail = true; await state.fetchLogs()
  assert.equal(state.logsData.value[0].id, 2); assert.equal(state.logSummaryData.value.tokens_total, 200); assert.equal(state.logState.isStale.value, true)
  fail = false; state.logStatusFilter.value = 'slow'; const old = state.searchLogs(); state.logStatusFilter.value = 'success'; await state.searchLogs()
  release({ data: { items: [{ id: 1 }], total: 1, summary: { tokens_total: 1 } } }); await old
  assert.equal(state.logsData.value[0].id, 2); assert.equal(state.logSummaryData.value.tokens_total, 200)
})
