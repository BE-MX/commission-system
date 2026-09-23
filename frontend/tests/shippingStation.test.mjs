import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { randomUUID } from 'node:crypto'
import { isShippingStationPath } from '../src/router/shippingStationRoute.js'

const source = fs.readFileSync(new URL('../src/views/shipping/composables/useShippingStation.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup(overrides = {}, compressor = async file => file, confirm = async () => {}, prepare = () => null) {
  const calls = [], timers = new Map()
  const people = [{ id: 1, name: '张三' }, { id: 2, name: '李四' }]
  const payload = { session_id: 'session-one', operator: people[1], record: { outbound_no: 'CK001' }, items: [], photos: [{ id: 5 }], videos: [], inspection: { status: 'draft', edit_version: 3, remark: '' } }
  const api = {
    operators: async () => ({ data: people }),
    scan: async body => { calls.push(['scan', body]); return { data: payload } },
    refresh: async () => ({ data: payload }),
    upload: async (id, type, form) => { calls.push(['upload', id, type, form.get('request_id'), form.get('edit_version')]); return { data: { id: 6 } } },
    submit: async (id, body) => { calls.push(['submit', body]); return { data: { operator_name: '李四', outbound_no: 'CK001' } } },
    end: async () => ({}), ...overrides,
  }
  let mounted
  const context = vm.createContext({
    ref: value => ({ value }), computed: getter => ({ get value() { return getter() } }),
    onMounted: fn => { mounted = fn }, onBeforeUnmount() {}, stationApi: api,
    confirmDanger: confirm, setTimeout: fn => { const id=randomUUID(); timers.set(id,fn); return id },
    clearTimeout: id => timers.delete(id), setInterval() {}, clearInterval() {},
    crypto: { randomUUID }, Date, FormData, Blob, console, AbortController, compressInspectionVideo: compressor, prepareInspectionVideo: prepare,
    window: { addEventListener() {}, removeEventListener() {} },
  })
  vm.runInContext(source + '\nthis.state=useShippingStation()', context)
  mounted()
  return { s: context.state, calls, timers, people }
}
const flush = () => new Promise(resolve => setImmediate(resolve))

test('no camera before explicit selection; rapid switching retains only latest identity', async () => {
  const { s, people, timers } = setup(); await flush()
  assert.equal(s.startScan(), false); assert.equal(s.scannerOpen.value, false)
  s.choose(people[0]); s.choose(people[1]); s.choose(people[0])
  for (const timer of timers.values()) timer()
  assert.equal(timers.size, 1); assert.equal(s.selected.value.name, '张三')
  assert.equal(s.startScan(), true)
  s.choose(people[1]); assert.equal(s.selected.value.id, 1)
})

test('scan freezes server-bound identity; submit uses returned edit version and clears next operator', async () => {
  const { s, people, calls } = setup(); await flush()
  s.choose(people[1]); await s.decoded('ARK-I:OB001:signature')
  s.choose(people[0]); assert.equal(s.operator.value.id, 2)
  await s.submit()
  assert.equal(calls.find(c => c[0] === 'submit')[1].edit_version, 3)
  assert.equal(s.selected.value, null); assert.equal(s.view.value, null)
  assert.equal(s.receipt.value.operator_name, '李四')
})

test('old evidence never satisfies recheck; each current item and whole order needs a fresh photo', async () => {
  const { s, people, calls } = setup(); await flush()
  s.choose(people[1]); await s.decoded('ARK-I:OB001:signature')
  s.view.value = { ...s.view.value, items: [{ item_id: 'IT001', product_name: 'Hair' }],
    required_recheck_ids: ['__all_items__', '__whole__'],
    photos: [{ id: 5, item_id: 'IT001', stale: true }] }
  assert.deepEqual(Array.from(s.missingRecheck.value), ['Hair', '整单'])
  await s.submit()
  assert.equal(calls.some(call => call[0] === 'submit'), false)
  s.view.value.photos.push({ id: 6, item_id: 'IT001', stale: false }, { id: 7, item_id: null, stale: false })
  assert.deepEqual(Array.from(s.missingRecheck.value), [])
})

test('uncertain upload retry keeps the same request id and version', async () => {
  const intents = []
  const { s, people } = setup({ upload: async (id, type, form) => { intents.push([form.get('request_id'), form.get('edit_version')]); if (intents.length === 1) throw new Error('lost response') } })
  await flush(); s.choose(people[1]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(new Blob(['image']), null, 'photos')
  assert.ok(s.pendingUpload.value)
  await s.retryUpload()
  assert.deepEqual(intents[0], intents[1]); assert.equal(s.pendingUpload.value, null)
})

test('uncertain submit locks edits and resolves original request rather than creating another', async () => {
  const bodies = []
  const { s, people } = setup({ refresh: async () => { throw new Error('must resolve submission before refresh') }, submit: async (id, body) => { bodies.push(body); if (bodies.length===1) throw new Error('lost response'); return { data: { operator_name:'李四' } } } })
  await flush(); s.choose(people[1]); await s.decoded('ARK-I:OB001:signature'); await s.submit()
  assert.equal(s.canWrite.value, false)
  await s.refresh(); assert.equal(s.error.value.includes('must resolve'), false)
  await s.submit(); assert.equal(bodies[0], bodies[1]); assert.equal(s.view.value, null)
})

test('role/session invalidation blocks writes and login route matches only the standalone target', async () => {
  const { s, people } = setup(); await flush(); s.choose(people[0])
  await s.fail({ response: { status:403, data:{ detail:{code:'OPERATOR_INVALID',message:'角色已撤销'} } } })
  assert.equal(s.selected.value, null); assert.equal(s.canWrite.value, false)
  assert.equal(isShippingStationPath('/shipping/scan?x=1'), true)
  assert.equal(isShippingStationPath('/shipping/scanner'), false)
  assert.equal(isShippingStationPath('//evil.test/shipping/scan'), false)
})

test('definitive stale-version rejection unlocks refresh instead of trapping an old submit intent', async () => {
  let refreshed = false
  const { s, people } = setup({
    submit: async () => { throw { response: { status:400, data:{detail:{code:'OPERATION_REJECTED',message:'版本已变更，请刷新'}} } } },
    refresh: async () => { refreshed = true; return {data:{session_id:'session-one',operator:people[1],photos:[],inspection:{status:'draft',edit_version:4}}} },
  })
  await flush(); s.choose(people[1]); await s.decoded('ARK-I:OB001:signature'); await s.submit()
  assert.equal(s.pendingSubmit.value, null)
  await s.refresh(); assert.equal(refreshed, true); assert.equal(s.view.value.inspection.edit_version, 4)
})


test('compression locks the session and uploads only the result; network retry does not recompress', async () => {
  let finish, count = 0
  const files = []
  const { s, people } = setup({ upload: async (_id, _type, form) => { files.push(await form.get('file').text()); if (files.length === 1) throw new Error('network') } }, () => { count++; return new Promise(resolve => { finish = resolve }) })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  const task = s.upload(new Blob(['original']), 'IT1', 'videos')
  assert.equal(s.busy.value, true)
  assert.equal(s.canWrite.value, false)
  await s.end(); assert.equal(s.sessionId.value, 'session-one')
  assert.equal(files.length, 0)
  finish(new Blob(['compressed']))
  await task; await s.retryUpload()
  assert.deepEqual(files, ['compressed', 'compressed'])
  assert.equal(count, 1)
  assert.equal(s.busy.value, false)
})

test('compression failure sends nothing and releases session lock', async () => {
  const { s, people, calls } = setup({}, async () => { throw new Error('视频压缩失败') })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(new Blob(['original']), null, 'videos')
  assert.equal(s.error.value, '视频压缩失败')
  assert.equal(s.busy.value, false)
  assert.equal(s.pendingUpload.value, null)
  assert.equal(calls.some(c => c[0] === 'upload'), false)
})

test('capture prepares before file selection, consumes preparation once and disposes cancelled selection', async () => {
  let disposed = 0, received
  const prepared = { dispose() { disposed++ } }
  const { s, people } = setup({}, async (file, options) => { received = options.prepared; return file }, undefined, () => prepared)
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  s.prepareVideo()
  await s.upload(new Blob(['video']), 'IT2', 'videos')
  assert.equal(received, prepared)
  s.cancelVideoPreparation()
  assert.equal(disposed, 0, 'consumed preparation is owned by the compressor')
  s.prepareVideo(); s.cancelVideoPreparation()
  assert.equal(disposed, 1)
})

test('Safari activation denial offers a normal start action without reporting failure', async () => {
  let attempts = 0
  const original = new Blob(['video']), products = []
  const { s, people, calls } = setup({ upload: async (_id, _type, form) => { products.push(form.get('item_id')) } }, async file => {
    assert.equal(file, original)
    if (++attempts === 1) throw Object.assign(new Error('User gesture required'), { code: 'VIDEO_ACTIVATION_REQUIRED' })
    return new Blob(['compressed'])
  })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(original, 'IT2', 'videos')
  assert.equal(s.error.value, '')
  assert.equal(s.uploadError.value, '')
  assert.equal(s.awaitingVideoActivation.value, true)
  assert.equal(s.busy.value, false)
  assert.equal(products.length, 0)
  await s.upload(new Blob(['photo']), 'IT1', 'photos')
  assert.equal(s.pendingCompression.value.file, original, 'another capture cannot silently replace this video')
  assert.equal(s.awaitingVideoActivation.value, true)
  await s.submit()
  assert.equal(calls.some(call => call[0] === 'submit'), false, 'do not submit before the selected video is uploaded')
  await s.retryCompression()
  assert.deepEqual(products, ['IT2'])
  assert.equal(s.awaitingVideoActivation.value, false)
  assert.equal(s.pendingCompression.value, null)
})

test('a broken video can be explicitly discarded to allow submission', async () => {
  const { s, people, calls } = setup({}, async () => { throw new Error('bad video') })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(new Blob(['bad']), 'IT2', 'videos')
  await s.discardCompression()
  assert.equal(s.pendingCompression.value, null)
  assert.equal(s.uploadError.value, '')
  await s.submit()
  assert.equal(calls.some(call => call[0] === 'submit'), true)
})

test('cancelling discard keeps the captured file available', async () => {
  const file = new Blob(['video'])
  const { s, people } = setup({}, async () => { throw new Error('bad video') }, async () => { throw new Error('cancel') })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(file, 'IT2', 'videos')
  await s.discardCompression()
  assert.equal(s.pendingCompression.value.file, file)
  assert.equal(s.busy.value, false)
})

test('compression can be retried by a new tap using the captured file and product', async () => {
  let attempts = 0
  const original = new Blob(['original']), files = [], products = []
  const { s, people } = setup({ upload: async (_id, _type, form) => { products.push(form.get('item_id')) } }, async file => {
    files.push(file)
    if (++attempts === 1) throw new Error('浏览器未允许视频处理')
    return new Blob(['compressed'])
  })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.upload(original, 'IT2', 'videos')
  assert.equal(s.uploadItemId.value, 'IT2')
  assert.equal(s.uploadError.value, '浏览器未允许视频处理')
  assert.equal(s.pendingCompression.value.file, original)
  await s.retryCompression()
  assert.deepEqual(files, [original, original])
  assert.deepEqual(products, ['IT2'])
  assert.equal(s.pendingCompression.value, null)
  assert.equal(s.uploadError.value, '')
})


test('return home ends the scanned session and requires choosing a person again', async () => {
  const ended = []
  const { s, people } = setup({ end: async id => { ended.push(id) } })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.end()
  assert.deepEqual(ended, ['session-one'])
  assert.equal(s.view.value, null)
  assert.equal(s.selected.value, null)
  assert.equal(s.startScan(), false)
})

test('failed session end preserves the current order and identity for retry', async () => {
  const { s, people } = setup({ end: async () => { throw new Error('offline') } })
  await flush(); s.choose(people[0]); await s.decoded('ARK-I:OB001:signature')
  await s.end()
  assert.equal(s.sessionId.value, 'session-one')
  assert.ok(s.operator.value)
  assert.equal(s.busy.value, false)
})
