import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import * as state from '../src/views/layout/favoriteNavigationState.js'

const tick = () => new Promise(resolve => setImmediate(resolve))
async function harness() {
  const queue = []
  let cleanup
  function request(kind, items, config) { return new Promise((resolve, reject) => queue.push({ kind, items, signal: config.signal, resolve, reject })) }
  const api = {
    getNavigationPreferences: config => request('get', null, config),
    saveNavigationPreferences: (items, config) => request('put', [...items], config),
  }
  const imports = { vue: { ...vue, onBeforeUnmount(fn) { cleanup = fn } }, '@/api/navigation': api, './favoriteNavigationState': state }
  const context = vm.createContext({ AbortController })
  const module = new vm.SourceTextModule(readFileSync(new URL('../src/views/layout/useFavoriteNavigation.js', import.meta.url), 'utf8'), { context })
  await module.link(name => {
    const values = imports[name]
    return new vm.SyntheticModule(Object.keys(values), function () { for (const key of Object.keys(values)) this.setExport(key, values[key]) }, { context })
  })
  await module.evaluate()
  const auth = vue.reactive({ user: { id: 1 } })
  const scope = vue.effectScope()
  const prefs = scope.run(() => module.namespace.useFavoriteNavigation(auth, vue.ref([{ name: 'A' }, { name: 'B' }])))
  async function finish(keys) { const gate = queue.shift(); gate.resolve({ data: { items: keys } }); await tick(); return gate }
  return { auth, prefs, queue, finish, dispose() { cleanup(); scope.stop() } }
}
test('old user load cannot replace new user preferences, including late responses after abort', async () => {
  const h = await harness()
  const old = h.queue.shift()
  h.auth.user = { id: 2 }
  assert.equal(old.signal.aborted, true)
  await h.finish(['B'])
  old.resolve({ data: { items: ['A'] } }); await tick()
  assert.deepEqual([...h.prefs.keys.value], ['B'])
  h.dispose()
})
test('save locks edits; a late response after account switch cannot change the new account', async () => {
  const h = await harness(); await h.finish(['A'])
  const saving = h.prefs.toggle('B'), old = h.queue.shift()
  assert.equal(h.prefs.locked.value, true)
  await h.prefs.toggle('A')
  assert.equal(h.queue.length, 0)
  h.auth.user = { id: 2 }
  await h.finish(['B'])
  old.resolve({ data: { items: ['A', 'B'] } }); await saving
  assert.deepEqual([...h.prefs.keys.value], ['B'])
  h.dispose()
})
test('uncertain write reads committed state and never automatically resends', async () => {
  const h = await harness(); await h.finish(['A'])
  const pending = h.prefs.toggle('B')
  h.queue.shift().reject(new Error('timeout')); await tick()
  assert.equal(h.queue[0].kind, 'get')
  await h.finish(['A', 'B']); await pending
  assert.deepEqual([...h.prefs.keys.value], ['A', 'B'])
  assert.equal(h.prefs.locked.value, false)
  assert.equal(h.queue.length, 0)
  assert.ok(h.prefs.error.value)
  h.dispose()
})
test('failed write and readback disable editing until successful reload', async () => {
  const h = await harness(); await h.finish(['A'])
  const pending = h.prefs.toggle('B')
  h.queue.shift().reject(new Error('offline')); await tick()
  h.queue.shift().reject(new Error('offline')); await pending
  assert.equal(h.prefs.locked.value, true)
  await h.prefs.toggle('A'); assert.equal(h.queue.length, 0)
  const reload = h.prefs.load(); await h.finish(['A']); await reload
  assert.equal(h.prefs.locked.value, false)
  assert.deepEqual([...h.prefs.keys.value], ['A'])
  h.dispose()
})
test('unauthorized navigation cannot be added through the composable', async () => {
  const h = await harness(); await h.finish(['A'])
  await h.prefs.toggle('Admin')
  assert.equal(h.queue.length, 0)
  assert.deepEqual([...h.prefs.keys.value], ['A'])
  h.dispose()
})
