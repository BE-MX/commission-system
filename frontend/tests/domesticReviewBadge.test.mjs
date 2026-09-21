import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { requestReviewsChanged, DOMESTIC_REVIEW_CHANGED } from '../src/utils/domesticReviewEvents.js'

const source = await readFile(new URL('../src/views/layout/useDomesticReviewBadge.js', import.meta.url), 'utf8')
const body = source.replace(/^import .*\r?\n/gm, '').replace('export function', 'function')

function setup() {
  const callbacks = {}, pending = [], listeners = new Map()
  const auth = { user: { id: 1 }, hasAnyPermission: () => true }
  const window = { setInterval(fn) { callbacks.timer = fn; return 1 }, clearInterval() { callbacks.timer = null },
    addEventListener(name, fn) { listeners.set(name, fn) }, removeEventListener(name) { listeners.delete(name) } }
  const document = { hidden: false, addEventListener(name, fn) { listeners.set(name, fn) }, removeEventListener(name) { listeners.delete(name) } }
  const factory = new Function('ref', 'watch', 'onMounted', 'onUnmounted', 'useAuthStore', 'getCustomerRequestPendingCount', 'DOMESTIC_REVIEW_CHANGED', 'window', 'document', body + ';return useDomesticReviewBadge()')
  const count = factory(value => ({ value }), (_id, fn) => { callbacks.watch = fn; fn() },
    fn => { callbacks.mount = fn }, fn => { callbacks.unmount = fn }, () => auth,
    () => new Promise(resolve => pending.push(resolve)), DOMESTIC_REVIEW_CHANGED, window, document)
  callbacks.mount()
  return { count, callbacks, pending, listeners, auth, document }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('count updates on mutation and polling; unmount removes listeners', async () => {
  const state = setup()
  state.pending.shift()({ data: { count: 3 } }); await flush()
  assert.equal(state.count.value, 3)
  state.listeners.get(DOMESTIC_REVIEW_CHANGED)()
  state.pending.shift()({ data: { count: 2 } }); await flush()
  assert.equal(state.count.value, 2)
  state.callbacks.timer()
  state.pending.shift()({ data: { count: 0 } }); await flush()
  assert.equal(state.count.value, 0)
  state.callbacks.unmount()
  assert.equal(state.listeners.size, 0)
  assert.equal(state.callbacks.timer, null)
})

test('logout invalidates an in-flight response and hidden tabs do not poll', async () => {
  const state = setup()
  state.auth.user = null
  state.callbacks.watch()
  state.pending.shift()({ data: { count: 9 } }); await flush()
  assert.equal(state.count.value, 0)
  state.auth.user = { id: 2 }
  state.document.hidden = true
  state.callbacks.timer()
  assert.equal(state.pending.length, 0)
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
