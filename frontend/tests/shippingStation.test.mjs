import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { randomUUID } from 'node:crypto'
import { isShippingStationPath } from '../src/router/shippingStationRoute.js'

const source = fs.readFileSync(new URL('../src/views/shipping/composables/useShippingStation.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup(overrides = {}) {
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
    confirmDanger: async () => {}, setTimeout: fn => { const id=randomUUID(); timers.set(id,fn); return id },
    clearTimeout: id => timers.delete(id), setInterval() {}, clearInterval() {},
    crypto: { randomUUID }, Date, FormData, Blob, console,
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
