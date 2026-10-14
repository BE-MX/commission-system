import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { requestReviewsChanged, DOMESTIC_REVIEW_CHANGED } from '../src/utils/domesticReviewEvents.js'

const source = await readFile(new URL('../src/views/layout/useDomesticReviewBadge.js', import.meta.url), 'utf8')
const body = source.replace(/^import .*\r?\n/gm, '').replace('export function', 'function')

function setup({ allowed = true, hidden = false } = {}) {
  const callbacks = {}, pending = [], listeners = new Map(), timeouts = new Map(), warnings = []
  let timeoutId = 0
  const auth = { user: { id: 1 }, allowed, hasAnyPermission() { return this.allowed } }
  const window = { setInterval(fn, delay) { callbacks.timer = fn; callbacks.interval = delay; return 1 }, clearInterval() { callbacks.timer = null },
    setTimeout(fn) { const id = ++timeoutId; timeouts.set(id, fn); return id }, clearTimeout(id) { timeouts.delete(id) },
    addEventListener(name, fn) { listeners.set(name, fn) }, removeEventListener(name) { listeners.delete(name) } }
  const document = { hidden, addEventListener(name, fn) { listeners.set(name, fn) }, removeEventListener(name) { listeners.delete(name) } }
  const factory = new Function('ref', 'watch', 'onMounted', 'onUnmounted', 'useAuthStore', 'getCustomerRequestPendingCount', 'DOMESTIC_REVIEW_CHANGED', 'window', 'document', 'console', body + ';return useDomesticReviewBadge()')
  const count = factory(value => ({ value }), (_id, fn) => { callbacks.watch = fn; fn() },
    fn => { callbacks.mount = fn }, fn => { callbacks.unmount = fn }, () => auth,
    config => new Promise((resolve, reject) => pending.push({ resolve, reject, config })), DOMESTIC_REVIEW_CHANGED, window, document,
    { warn: (...args) => warnings.push(args) })
  callbacks.mount()
  const resume = () => { for (const [id, fn] of [...timeouts]) { timeouts.delete(id); fn() } }
  return { count, callbacks, pending, listeners, auth, document, timeouts, warnings, resume }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('count updates on mutation and polls every 60 seconds; unmount removes listeners', async () => {
  const state = setup()
  assert.equal(state.callbacks.interval, 60000)
  state.pending.shift().resolve({ data: { count: 3 } }); await flush()
  assert.equal(state.count.value, 3)
  state.listeners.get(DOMESTIC_REVIEW_CHANGED)()
  state.pending.shift().resolve({ data: { count: 2 } }); await flush()
  assert.equal(state.count.value, 2)
  state.callbacks.timer()
  state.pending.shift().resolve({ data: { count: 0 } }); await flush()
  assert.equal(state.count.value, 0)
  state.callbacks.unmount()
  assert.equal(state.listeners.size, 0)
  assert.equal(state.callbacks.timer, null)
})

test('logout invalidates an in-flight response and hidden tabs do not poll', async () => {
  const state = setup()
  const old = state.pending.shift()
  state.auth.user = null
  state.callbacks.watch()
  assert.equal(old.config.signal.aborted, true)
  old.resolve({ data: { count: 9 } }); await flush()
  assert.equal(state.count.value, null)
  state.auth.user = { id: 2 }
  state.document.hidden = true
  state.callbacks.timer()
  assert.equal(state.pending.length, 0)
})

async function succeed(state, count) { state.pending.shift().resolve({ data: { count } }); await flush() }

test('focus and visibility events coalesce and slow polling does not overlap', async () => {
  const state = setup()
  await succeed(state, 3)
  state.listeners.get('visibilitychange')()
  state.listeners.get('focus')()
  assert.equal(state.timeouts.size, 1)
  state.resume()
  assert.equal(state.pending.length, 1)
  state.callbacks.timer()
  state.listeners.get('focus')()
  state.resume()
  assert.equal(state.pending.length, 1)
  await succeed(state, 4)
  assert.equal(state.count.value, 4)
  assert.equal(state.pending.length, 0)
})

test('mutations during a slow read schedule exactly one fresh read afterwards', async () => {
  const state = setup()
  const first = state.pending[0]
  for (let i = 0; i < 3; i++) state.listeners.get(DOMESTIC_REVIEW_CHANGED)()
  assert.equal(state.pending.length, 1)
  await succeed(state, 3)
  assert.equal(state.pending.length, 1)
  assert.notEqual(state.pending[0], first)
  await succeed(state, 1)
  assert.equal(state.count.value, 1)
  assert.equal(state.pending.length, 0)
})

test('failed or malformed reads retain the last known count and later polling recovers', async () => {
  const state = setup()
  await succeed(state, 7)
  state.callbacks.timer()
  state.pending.shift().reject(new Error('offline')); await flush()
  assert.equal(state.count.value, 7)
  state.callbacks.timer()
  state.pending.shift().resolve({ data: {} }); await flush()
  assert.equal(state.count.value, 7)
  assert.equal(state.warnings.length, 2)
  state.callbacks.timer()
  await succeed(state, 2)
  assert.equal(state.count.value, 2)
})

test('first-load failure stays unknown rather than reporting zero', async () => {
  const state = setup()
  state.pending.shift().reject(new Error('offline')); await flush()
  assert.equal(state.count.value, null)
})

test('hidden tabs and accounts without review permissions do not query', () => {
  for (const options of [{ hidden: true }, { allowed: false }]) {
    const state = setup(options)
    state.callbacks.timer()
    state.listeners.get('focus')()
    state.resume()
    assert.equal(state.pending.length, 0)
    assert.equal(state.count.value, null)
  }
})

test('account changes abort old reads and reject stale responses', async () => {
  const state = setup()
  const old = state.pending.shift()
  state.auth.user = { id: 2 }
  state.callbacks.watch()
  assert.equal(old.config.signal.aborted, true)
  await succeed(state, 2)
  old.resolve({ data: { count: 99 } }); await flush()
  assert.equal(state.count.value, 2)
})

test('permission loss clears the previous count and cancels its pending read', async () => {
  const state = setup()
  await succeed(state, 7)
  state.callbacks.timer()
  const old = state.pending.shift()
  state.auth.allowed = false
  state.callbacks.watch()
  assert.equal(old.config.signal.aborted, true)
  old.resolve({ data: { count: 99 } }); await flush()
  state.callbacks.timer()
  assert.equal(state.count.value, null)
  assert.equal(state.pending.length, 0)
})

test('hiding a tab cancels its scheduled resume until it becomes visible', async () => {
  const state = setup()
  await succeed(state, 3)
  state.listeners.get('focus')()
  state.document.hidden = true
  state.listeners.get('visibilitychange')()
  state.resume()
  state.callbacks.timer()
  assert.equal(state.pending.length, 0)
  state.document.hidden = false
  state.listeners.get('visibilitychange')()
  state.resume()
  await succeed(state, 2)
  assert.equal(state.count.value, 2)
})

test('unmount aborts transport, removes listeners and cancels a scheduled resume', async () => {
  const state = setup()
  const old = state.pending.shift()
  const staleTimer = state.callbacks.timer
  state.listeners.get('focus')()
  state.callbacks.unmount()
  assert.equal(old.config.signal.aborted, true)
  assert.equal(state.listeners.size, 0)
  assert.equal(state.timeouts.size, 0)
  assert.equal(state.callbacks.timer, null)
  old.reject({ code: 'ERR_CANCELED' }); await flush()
  staleTimer()
  state.resume()
  assert.equal(state.pending.length, 0)
  assert.equal(state.warnings.length, 0)
})

test('pending-count API is always quiet and forwards transport cancellation', async () => {
  const requests = [], controller = new AbortController(), context = vm.createContext({})
  const apiSource = await readFile(new URL('../src/api/domestic.js', import.meta.url), 'utf8')
  const api = new vm.SourceTextModule(apiSource, { context })
  await api.link(name => {
    const exports = name === './clients'
      ? { domesticClient: { get: (path, config) => { requests.push({ path, config }); return Promise.resolve({ data: { count: 3 } }) } } }
      : { requestReviewsChanged }
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [name, value] of Object.entries(exports)) this.setExport(name, value)
    }, { context })
  })
  await api.evaluate()
  await api.namespace.getCustomerRequestPendingCount({ signal: controller.signal, showLoading: true, suppressToast: false })
  assert.equal(requests[0].path, '/customer-requests/pending-count')
  assert.equal(requests[0].config.showLoading, false)
  assert.equal(requests[0].config.suppressToast, true)
  assert.equal(requests[0].config.signal, controller.signal)
})

test('only successful mutations emit the badge refresh event', async () => {
  globalThis.window = new EventTarget()
  let events = 0
  window.addEventListener(DOMESTIC_REVIEW_CHANGED, () => events++)
  assert.equal(await requestReviewsChanged(Promise.resolve(42)), 42)
  await assert.rejects(requestReviewsChanged(Promise.reject(new Error('failed'))))
  assert.equal(events, 1)
  delete globalThis.window
})
