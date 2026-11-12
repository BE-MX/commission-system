import assert from 'node:assert/strict'
import { test } from 'node:test'
import fs from 'node:fs/promises'
import vm from 'node:vm'
import * as vue from 'vue'
import * as controller from '../src/views/client_desk/deskController.js'

const day = '2026-11-12'
const tick = () => new Promise(resolve => setImmediate(resolve))
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const card = id => ({ company_id: String(id), name: `Customer ${id}`, rule_codes: ['R2_FOLLOWUP_DUE'] })
const dossier = id => ({ card: card(id), personal_state: {} })

async function harness(overrides = {}) {
  const calls = [], timers = new Map(), cleanups = []
  let timerId = 0, now = 0
  const defaults = { today: async () => ({ biz_date: day, items: [card(1), card(2)], counts: {} }), customers: async () => ({ items: [card(1)], total: 1 }), customer: async id => dossier(id), timeline: async () => ({ items: [], next_cursor: null }), feedback: async () => ({}) }
  const api = Object.fromEntries(Object.entries({ ...defaults, ...overrides }).map(([name, fn]) => [name, (...args) => { calls.push([name, ...args]); return fn(...args) }]))
  const context = vm.createContext({ AbortController, Date: { now: () => now }, setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id }, clearTimeout: id => timers.delete(id) })
  const modules = {
    vue: { ...vue, onBeforeUnmount: fn => cleanups.push(fn) },
    '@/api/clientDesk': { clientDeskApi: api }, '@/utils/feedback': { msgSuccessText: () => {} },
    '@/utils/datetime': { currentBeijingDate: () => day, formatBeijingDateTime: () => `${day} 10:00:00` },
    './deskController': controller,
  }
  const code = await fs.readFile(new URL('../src/views/client_desk/useClientDesk.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(code, { context })
  await module.link(name => {
    const values = modules[name]
    if (!values) throw new Error(`Unexpected import ${name}`)
    return new vm.SyntheticModule(Object.keys(values), function () { for (const [key, value] of Object.entries(values)) this.setExport(key, value) }, { context })
  })
  await module.evaluate()
  const scope = vue.effectScope()
  const state = scope.run(() => module.namespace.useClientDesk({ query: {} }))
  return { state, calls, timers, advance: value => { now += value }, stop: () => { cleanups.forEach(fn => fn()); scope.stop() } }
}

test('dossier is displayed before timeline settles; timeline failure has its own retry', async () => {
  const pending = deferred()
  let count = 0
  const h = await harness({ timeline: () => ++count === 1 ? pending.promise : Promise.resolve({ items: [{ id: 'retry' }] }) })
  try {
    await h.state.select(card(1))
    assert.deepEqual(h.calls.map(c => c[0]), ['timeline', 'customer'])
    assert.equal(h.state.detail.value.card.company_id, '1')
    assert.equal(h.state.detailLoading.value, false)
    assert.equal(h.state.timelineLoading.value, true)
    pending.reject(new Error('Timeline unavailable'))
    await tick()
    assert.equal(h.state.timelineError.value, 'Timeline unavailable')
    assert.equal(h.state.detailError.value, '')
    assert.equal(h.state.detail.value.card.company_id, '1')
    await h.state.loadTimeline()
    assert.equal(h.state.events.value[0].id, 'retry')
    assert.equal(h.calls.filter(c => c[0] === 'customer').length, 1)
  } finally { h.stop() }
})

test('switching customers rejects late dossier and timeline responses', async () => {
  const oldDetail = deferred(), oldTimeline = deferred()
  const h = await harness({ customer: id => id === '1' ? oldDetail.promise : Promise.resolve(dossier(id)), timeline: id => id === '1' ? oldTimeline.promise : Promise.resolve({ items: [{ id: 'B' }] }) })
  try {
    const old = h.state.select(card(1))
    await h.state.select(card(2))
    oldDetail.resolve(dossier(1)); oldTimeline.resolve({ items: [{ id: 'A' }] })
    await old; await tick()
    assert.equal(h.state.detail.value.card.company_id, '2')
    assert.equal(h.state.events.value[0].id, 'B')
    assert.equal(h.calls.find(c => c[0] === 'customer' && c[1] === '1')[2].aborted, true)
  } finally { h.stop() }
})

test('today initial data serves paging and filters once, explicit refresh and 15s expiry reload', async () => {
  const h = await harness({ today: async () => ({ biz_date: day, items: Array.from({ length: 25 }, (_, i) => card(i + 1)), counts: {} }) })
  try {
    await h.state.init()
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 1)
    assert.equal(h.state.rows.value.length, 20)
    h.state.page.value = 2; await tick()
    assert.equal(h.state.rows.value.length, 5)
    assert.equal(h.state.total.value, 25)
    assert.equal(h.calls.filter(c => c[0] === 'customers').length, 0)
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 1)
    await h.state.loadList()
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 2)
    h.advance(15000)
    h.state.page.value = 1; await tick()
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 3)
    h.state.mode.value = 'all'; await tick()
    h.state.mode.value = 'suggested'; await tick()
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 4)
  } finally { h.stop() }
})

test('post-write refresh supersedes a pre-write today request', async () => {
  const old = deferred()
  let reads = 0
  const h = await harness({ today: () => ++reads === 1 ? old.promise : Promise.resolve({ biz_date: day, items: [card(2)] }) })
  try {
    const initial = h.state.init()
    h.state.selected.value = '1'
    h.state.detail.value = { suggestion: { id: '7' } }
    await h.state.feedback('done')
    assert.equal(reads, 2)
    old.resolve({ biz_date: day, items: [card(1)] }); await initial
    assert.equal(h.state.today.value.items[0].company_id, '2')
    assert.equal(h.state.rows.value[0].company_id, '2')
  } finally { h.stop() }
})

test('analysis polling updates only the dossier and never aborts a slow timeline', async () => {
  const pending = deferred()
  let reads = 0
  const h = await harness({ customer: async id => ({ ...dossier(id), suggestion: { id: '7', status: ++reads < 3 ? 'running' : 'succeeded' } }), timeline: () => pending.promise })
  try {
    await h.state.select(card(1))
    const signal = h.calls.find(c => c[0] === 'timeline')[3]
    for (let i = 0; i < 2; i++) {
      const [id, timer] = [...h.timers].find(([, item]) => item.delay === 5000)
      h.timers.delete(id); await timer.fn(); await tick()
    }
    assert.equal(reads, 3)
    assert.equal(h.calls.filter(c => c[0] === 'timeline').length, 1)
    assert.equal(signal.aborted, false)
    pending.resolve({ items: [{ id: 'slow-complete' }] }); await tick()
    assert.equal(h.state.events.value[0].id, 'slow-complete')
    assert.equal(h.calls.filter(c => c[0] === 'timeline').length, 2)
    assert.equal(h.calls.filter(c => c[0] === 'today').length, 1)
  } finally { h.stop() }
})

test('paging during an explicit refresh waits for the new today snapshot', async () => {
  const pending = deferred()
  let reads = 0
  const h = await harness({ today: () => ++reads === 1 ? Promise.resolve({ biz_date: day, items: Array.from({ length: 25 }, (_, i) => card(i)) }) : pending.promise })
  try {
    await h.state.init()
    const refresh = h.state.loadList()
    h.state.page.value = 2; await tick()
    assert.equal(h.state.rows.value.length, 0)
    pending.resolve({ biz_date: day, items: Array.from({ length: 25 }, (_, i) => card(i + 100)) })
    await refresh; await tick()
    assert.equal(h.state.rows.value[0].company_id, '120')
    assert.equal(h.state.today.value.items[0].company_id, '100')
    assert.equal(h.state.loading.value, false)
    assert.equal(reads, 2)
  } finally { h.stop() }
})

test('today search keeps Unicode case folding and filters before pagination', () => {
  const items = [{ ...card(1), name: 'Straße' }, { ...card(2), name: 'ΟΣ' }, { ...card(3), name: 'Other', rule_codes: [] }]
  assert.equal(controller.suggestedPage(items, { keyword: 'STRASSE' }).items[0].company_id, '1')
  assert.equal(controller.suggestedPage(items, { keyword: 'ος' }).items[0].company_id, '2')
  const result = controller.suggestedPage(items, { reason: 'R2_FOLLOWUP_DUE', page: 2, pageSize: 1 })
  assert.equal(result.total, 2)
  assert.equal(result.items[0].company_id, '2')
})

test('copy API explicitly bypasses ownership cache while ordinary dossier reads do not', async () => {
  const calls = []
  const client = { get: async (...args) => { calls.push(args); return { data: {} } } }
  const context = vm.createContext({})
  const module = new vm.SourceTextModule(await fs.readFile(new URL('../src/api/clientDesk.js', import.meta.url), 'utf8'), { context })
  await module.link(name => {
    assert.equal(name, './clients')
    return new vm.SyntheticModule(['clientDeskClient', 'clientDeskPublicClient'], function () {
      this.setExport('clientDeskClient', client); this.setExport('clientDeskPublicClient', client)
    }, { context })
  })
  await module.evaluate()
  await module.namespace.clientDeskApi.customer('801')
  await module.namespace.clientDeskApi.freshCustomer('801')
  assert.equal(calls[0][1].params, undefined)
  assert.equal(calls[1][0], '/customers/801')
  assert.equal(calls[1][1].params.fresh, true)
})
