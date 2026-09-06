import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

function harness() {
  const hooks = {}
  const timers = new Map()
  const pending = []
  let timerId = 0
  const source = fs.readFileSync(new URL('../src/views/system/composables/useOperationsCenter.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace('export function', 'function')
  const context = {
    ref: value => ({ value }), computed: read => ({ get value() { return read() } }),
    operationsClient: { get: () => new Promise(resolve => pending.push(resolve)) },
    onMounted: fn => { hooks.mount = fn }, onActivated: fn => { hooks.activate = fn },
    onBeforeUnmount: fn => { hooks.unmount = fn }, onDeactivated: fn => { hooks.deactivate = fn },
    window: { setInterval: fn => { timers.set(++timerId, fn); return timerId }, clearInterval: id => timers.delete(id) },
    document: { hidden: false },
  }
  vm.createContext(context)
  vm.runInContext(source + '\nthis.api = useOperationsCenter()', context)
  return { ...context, hooks, timers, pending }
}

test('a background refresh cannot strand an interactive loading indicator', async () => {
  const h = harness()
  const interactive = h.api.loadDashboard()
  const background = h.api.loadDashboard({ quiet: true })
  assert.equal(h.api.loading.value, true)
  h.pending[0]({ data: {} }); h.pending[1]({ data: [] })
  await interactive
  assert.equal(h.api.loading.value, false)
  h.pending[2]({ data: {} }); h.pending[3]({ data: [] })
  await background
})

test('cached pages stop polling while inactive and only create one timer on activation', async () => {
  const h = harness()
  h.hooks.mount()
  h.hooks.activate?.()
  assert.equal(h.timers.size, 1)
  assert.equal(h.pending.length, 2)
  h.hooks.deactivate()
  assert.equal(h.timers.size, 0)
  h.hooks.activate()
  assert.equal(h.timers.size, 1)
  h.document.hidden = true
  const count = h.pending.length
  h.timers.values().next().value()
  assert.equal(h.pending.length, count)
  h.hooks.unmount()
  assert.equal(h.timers.size, 0)
  for (const resolve of h.pending) resolve({ data: [] })
})
