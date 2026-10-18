import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import { webcrypto } from 'node:crypto'

const tick = () => new Promise(resolve => setImmediate(resolve))
async function harness() {
  const queue = [], timers = new Map(), cleanup = []
  let timerUid = 0
  const context = vm.createContext({ AbortController, Date, Intl, crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
    setTimeout: fn => { timers.set(++timerUid, fn); return timerUid }, clearTimeout: uid => timers.delete(uid) })
  const synthetic = exports => new vm.SyntheticModule(Object.keys(exports), function () { for (const [name, value] of Object.entries(exports)) this.setExport(name, value) }, { context })
  const dates = new vm.SourceTextModule(fs.readFileSync(new URL('../src/utils/datetime.js', import.meta.url), 'utf8'), { context })
  await dates.link(() => { throw new Error('Unexpected date import') }); await dates.evaluate()
  const keys = new vm.SourceTextModule(fs.readFileSync(new URL('../src/utils/requestKey.js', import.meta.url), 'utf8'), { context })
  await keys.link(() => { throw new Error('Unexpected key import') }); await keys.evaluate()
  const names = ['getWhatsAppAssistantOptions', 'createWhatsAppAssistantRun', 'listWhatsAppAssistantRuns', 'getWhatsAppAssistantRun', 'getWhatsAppAssistantRequest', 'updateWhatsAppAssistantTask']
  const api = Object.fromEntries(names.map(name => [name, (...args) => new Promise((resolve, reject) => queue.push({ name, args, resolve, reject }))]))
  const module = new vm.SourceTextModule(fs.readFileSync(new URL('../src/views/system/composables/useWhatsAppAssistant.js', import.meta.url), 'utf8'), { context })
  await module.link(name => name.endsWith('/requestKey.js') ? keys : name.endsWith('/datetime') ? dates : synthetic(name === 'vue' ? { ...vue, onUnmounted: fn => cleanup.push(fn) } : api))
  await module.evaluate()
  const props = vue.reactive({ modelValue: true, account: { account_uid: 'test', can_read_body: true, consent_version: 1, ai_egress_allowed: true }, accessKey: 'owner', conversation: { conversation_uid: 'chat' } })
  const state = module.namespace.useWhatsAppAssistant(props, () => { props.modelValue = false })
  const take = name => { const index = queue.findIndex(item => item.name === name); assert.ok(index >= 0, name); return queue.splice(index, 1)[0] }
  async function initialized() {
    take('getWhatsAppAssistantOptions').resolve({ data: { can_analyze: true, limits: { max_days: 31 } } })
    take('listWhatsAppAssistantRuns').resolve({ data: { items: [] } }); await tick()
  }
  return { state, props, queue, timers, cleanup, take, initialized, exports: module.namespace }
}

test('Beijing defaults cross midnight independent of browser timezone, inclusive endpoints and max span', async () => {
  const h = await harness()
  const previous = process.env.TZ
  try {
    process.env.TZ = 'America/Los_Angeles'
    assert.deepEqual(Array.from(h.exports.defaultAssistantRange(new Date('2026-10-12T16:30:00Z'))), ['2026-10-06 00:30:00', '2026-10-13 00:30:00'])
    assert.equal(h.exports.assistantRangeError(['2026-10-13 00:00:00', '2026-10-13 00:00:00']), '')
    assert.match(h.exports.assistantRangeError(['2026-09-01 00:00:00', '2026-10-13 00:00:00']), /31/)
    assert.match(h.exports.assistantRangeError(['2026-10-14 00:00:00', '2026-10-13 00:00:00']), /早于/)
  } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous }
})

test('uncertain submission queries original UID, never resends, and persists across close', async () => {
  const h = await harness(); await h.initialized()
  h.state.range.value = ['2026-10-13 00:00:00', '2026-10-13 23:59:59']
  const pending = h.state.createRun(), post = h.take('createWhatsAppAssistantRun')
  assert.equal(post.args[0].start_at, '2026-10-13T00:00:00+08:00')
  assert.equal(post.args[0].conversation_uid, null)
  const originalUid = post.args[0].client_request_uid
  assert.match(originalUid, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  post.reject(new Error('connection interrupted')); await tick()
  h.take('getWhatsAppAssistantRequest').reject({ response: { status: 404 } }); await pending
  assert.equal(h.state.unresolvedUid.value, originalUid)
  await h.state.createRun(); assert.equal(h.queue.length, 0)
  h.props.modelValue = false; await tick(); h.props.modelValue = true; await tick(); await h.initialized()
  const lookup = h.take('getWhatsAppAssistantRequest')
  assert.equal(lookup.args[0], originalUid)
  assert.deepEqual(Array.from(h.state.range.value), ['2026-10-13 00:00:00', '2026-10-13 23:59:59'])
  lookup.resolve({ data: { run_uid: 'saved', status: 'running' } }); await tick()
  assert.equal(h.state.run.value.run_uid, 'saved'); assert.equal(h.timers.size, 1)
  h.props.modelValue = false; await tick(); assert.equal(h.timers.size, 0)
})

test('old account response and polling cannot overwrite current authority', async () => {
  const h = await harness(); await h.initialized()
  const pending = h.state.createRun(), old = h.take('createWhatsAppAssistantRun')
  h.props.account = { account_uid: 'other', can_read_body: true, consent_version: 1 }; await tick()
  assert.equal(old.args[1].signal.aborted, true)
  old.resolve({ data: { run_uid: 'old', status: 'succeeded', results: [{ summary: 'secret' }] } }); await pending
  assert.equal(h.state.run.value, null); assert.equal(h.props.modelValue, false); assert.equal(h.timers.size, 0)
})

test('checklist is server-confirmed and permission revocation clears report', async () => {
  const h = await harness(); await h.initialized()
  const selecting = h.state.selectRun('saved')
  h.take('getWhatsAppAssistantRun').resolve({ data: { run_uid: 'saved', status: 'succeeded', results: [] } }); await selecting
  const patching = h.state.setTaskCompleted({ task_uid: 'task' }, true), patch = h.take('updateWhatsAppAssistantTask')
  assert.equal(patch.args[2], true)
  h.props.account.can_read_body = false; await tick()
  patch.resolve({ data: { run_uid: 'saved', status: 'succeeded', results: [{ summary: 'secret' }] } }); await patching
  assert.equal(h.state.run.value, null)
})

test('idempotent POST terminal metadata fetches full detail, current-chat scope cannot silently become whole account', async () => {
  const h = await harness(); await h.initialized()
  h.state.scope.value = 'current'; h.props.conversation = null; await tick()
  assert.equal(h.state.canCreate.value, false)
  h.props.conversation = { conversation_uid: 'chat' }; await tick()
  const creating = h.state.createRun(), post = h.take('createWhatsAppAssistantRun')
  assert.equal(post.args[0].conversation_uid, 'chat')
  post.resolve({ data: { run_uid: 'saved', status: 'succeeded' } }); await tick()
  h.take('getWhatsAppAssistantRun').resolve({ data: { run_uid: 'saved', status: 'succeeded', results: [{ summary: 'full detail' }] } }); await creating
  assert.equal(h.state.run.value.results[0].summary, 'full detail')
})

test('404 alone never resends; explicit retry uses original UID and payload despite draft changes', async () => {
  const h = await harness(); await h.initialized()
  h.state.scope.value = 'current'
  h.state.range.value = ['2026-10-13 00:00:00', '2026-10-13 23:59:59']
  const creating = h.state.createRun(), original = h.take('createWhatsAppAssistantRun')
  const payload = JSON.parse(JSON.stringify(original.args[0]))
  original.reject(new Error('connection interrupted')); await tick()
  h.take('getWhatsAppAssistantRequest').reject({ response: { status: 404 } }); await creating
  assert.equal(h.state.canRetryRequest.value, true); assert.equal(h.queue.length, 0)
  h.state.range.value = ['2026-10-01 00:00:00', '2026-10-02 00:00:00']
  h.state.scope.value = 'all'; h.props.conversation = { conversation_uid: 'another' }
  const retrying = h.state.retryRequest(), retry = h.take('createWhatsAppAssistantRun')
  assert.deepEqual(JSON.parse(JSON.stringify(retry.args[0])), payload)
  await h.state.retryRequest(); assert.equal(h.queue.length, 0)
  retry.resolve({ data: { run_uid: 'saved', status: 'running' } }); await retrying
  assert.equal(h.timers.size, 1)
  h.props.modelValue = false; await tick(); assert.equal(h.timers.size, 0)
})

test('retry response after authority change cannot restore old result or restart polling', async () => {
  const h = await harness(); await h.initialized()
  const creating = h.state.createRun(), original = h.take('createWhatsAppAssistantRun')
  original.reject(new Error('connection interrupted')); await tick()
  h.take('getWhatsAppAssistantRequest').reject({ response: { status: 404 } }); await creating
  const retrying = h.state.retryRequest(), retry = h.take('createWhatsAppAssistantRun')
  h.props.accessKey = 'different-user'; await tick()
  assert.equal(retry.args[1].signal.aborted, true)
  retry.resolve({ data: { run_uid: 'saved', status: 'succeeded', results: [{ summary: 'secret' }] } }); await retrying
  assert.equal(h.state.run.value, null); assert.equal(h.timers.size, 0)
})

test('409 checklist failure clears old summary immediately and reads stale report', async () => {
  const h = await harness(); await h.initialized()
  const selecting = h.state.selectRun('saved')
  h.take('getWhatsAppAssistantRun').resolve({ data: { run_uid: 'saved', status: 'succeeded', results: [{ summary: 'old secret' }] } }); await selecting
  const patching = h.state.setTaskCompleted({ task_uid: 'task' }, true)
  h.take('updateWhatsAppAssistantTask').reject({ response: { status: 409 } }); await tick()
  assert.equal(h.state.run.value, null)
  h.take('getWhatsAppAssistantRun').resolve({ data: { run_uid: 'saved', status: 'stale', results: [], error_message: 'source changed' } }); await patching
  assert.equal(h.state.run.value.status, 'stale'); assert.equal(h.state.run.value.results.length, 0)
})
