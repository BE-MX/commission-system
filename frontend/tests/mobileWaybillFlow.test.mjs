import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import fs from 'node:fs/promises'
import * as vue from 'vue'
import * as controller from '../src/views/shipping/composables/mobileWaybillState.js'
const row = { id: 1, recipient_name: 'Alice', recipient_country: 'US', edit_version: 2, shipment_version: 3 }
const result = { preview_token: 'signed', format_valid: true, can_submit: true, existing: { exists: false }, warnings: [], sync_result: 'not_found' }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
async function harness(overrides = {}) {
  const calls = [], cleanups = []
  const defaults = { listMobileWaybillQueue: async () => ({ data: { items: [row], total: 1, has_more: false } }),
    uploadInspectionWaybillPhoto: async () => ({ data: { photo_token: 'photo', waybill_no: '1234567890', carrier: 'DHL', number_source: 'barcode' } }),
    previewInspectionShipment: async () => ({ data: result }), createInspectionShipment: async () => ({ data: {} }), bindInspectionShipment: async () => ({ data: {} }) }
  const api = Object.fromEntries(Object.entries({ ...defaults, ...overrides }).map(([name, fn]) => [name, (...args) => { calls.push([name, ...args]); return fn(...args) }]))
  const context = vm.createContext({ setTimeout, clearTimeout, FormData, URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} } })
  const modules = { vue: { ...vue, onMounted: () => {}, onBeforeUnmount: fn => cleanups.push(fn) },
    'element-plus': { ElMessageBox: { confirm: async () => {} } }, '@/stores/auth': { useAuthStore: () => ({ hasPermission: () => true }) },
    '@/utils/datetime': { currentBeijingDate: () => '2026-11-23' }, '@/utils/feedback': { msgSuccessText: () => {}, confirmAction: async () => {} }, '@/api/shipping': api, './mobileWaybillState.js': controller }
  const module = new vm.SourceTextModule(await fs.readFile(new URL('../src/views/shipping/composables/useMobileWaybills.js', import.meta.url), 'utf8'), { context })
  await module.link(name => new vm.SyntheticModule(Object.keys(modules[name]), function () { for (const [key, value] of Object.entries(modules[name])) this.setExport(key, value) }, { context }))
  await module.evaluate()
  const scope = vue.effectScope(), state = scope.run(() => module.namespace.useMobileWaybills())
  await state.begin(row)
  const photo = { scan: new Blob(['scan']), original: new Blob(['original']), barcode: '1234567890' }
  return { state, calls, photo, stop: () => { cleanups.forEach(fn => fn()); scope.stop() } }
}
test('late photo response cannot overwrite another inspection session', async () => {
  const pending = deferred(), h = await harness({ uploadInspectionWaybillPhoto: () => pending.promise })
  try { const first = h.state.captured(h.photo); h.state.back(); await h.state.begin({ ...row, id: 2 }); pending.resolve({ data: { photo_token: 'old', waybill_no: '9999999999' } }); await first; assert.equal(h.state.photoToken.value, ''); assert.equal(h.state.form.waybill_no, '') } finally { h.stop() }
})
test('editing signed fields invalidates in-flight preview response', async () => {
  const pending = deferred(), h = await harness({ previewInspectionShipment: () => pending.promise })
  try { await h.state.captured(h.photo); const sync = h.state.sync(); h.state.form.recipient_country = 'DE'; pending.resolve({ data: result }); await sync; assert.equal(h.state.preview.value, null); assert.equal(h.state.canSubmit.value, false) } finally { h.stop() }
})
test('submit timeout retry preserves the same photo and preview evidence', async () => {
  let count = 0
  const h = await harness({ createInspectionShipment: async () => { if (++count === 1) throw new Error('timeout'); return { data: {} } } })
  try { await h.state.captured(h.photo); await h.state.sync(); await h.state.submit(); assert.equal(h.state.canSubmit.value, true); await h.state.submit(); const writes = h.calls.filter(call => call[0] === 'createInspectionShipment'); assert.equal(writes.length, 2); assert.equal(JSON.stringify(writes[0][2]), JSON.stringify(writes[1][2])); assert.equal(h.state.step.value, 'list') } finally { h.stop() }
})
test('existing carrier display does not change signed input or enable duplicate submits', async () => {
  const pending = deferred()
  const h = await harness({ previewInspectionShipment: async () => ({ data: { ...result, existing: { exists: true, carrier: '未知' } } }), bindInspectionShipment: () => pending.promise })
  try { await h.state.captured(h.photo); await h.state.sync(); assert.equal(h.state.form.carrier, 'DHL'); const first = h.state.submit(); await h.state.submit(); assert.equal(h.calls.filter(call => call[0] === 'bindInspectionShipment').length, 1); pending.resolve({ data: {} }); await first } finally { h.stop() }
})

test('completion reloads loaded pages once and focuses the original next card', async () => {
  let completed = false
  const cards = [1, 2, 3, 4].map(id => ({ ...row, id }))
  const h = await harness({ listMobileWaybillQueue: async params => ({ data: { items: completed ? (params.page === 1 ? [cards[0], cards[2]] : [cards[3]]) : (params.page === 1 ? cards.slice(0, 2) : cards.slice(2)), total: completed ? 3 : 4, has_more: params.page === 1 } }), createInspectionShipment: async () => { completed = true; return { data: {} } } })
  try {
    await h.state.loadQueue(); await h.state.loadMore(); await h.state.begin(cards[1])
    await h.state.captured(h.photo); await h.state.sync(); const before = h.calls.filter(call => call[0] === 'listMobileWaybillQueue').length
    await h.state.submit()
    assert.deepEqual(Array.from(h.state.rows.value, item => item.id), [1, 3, 4]); assert.equal(h.state.nextInspectionId.value, 3)
    assert.deepEqual(h.calls.filter(call => call[0] === 'listMobileWaybillQueue').slice(before).map(call => call[1].page), [1, 2])
  } finally { h.stop() }
})
test('replacement switches from done to pending with one refresh and focuses its first card', async () => {
  const h = await harness()
  try {
    h.state.tab.value = 'done'; await vue.nextTick(); await h.state.begin(row); await h.state.captured(h.photo); await h.state.sync()
    const before = h.calls.filter(call => call[0] === 'listMobileWaybillQueue').length
    await h.state.submit(); await vue.nextTick()
    assert.equal(h.state.tab.value, 'pending'); assert.equal(h.state.nextInspectionId.value, 1)
    assert.equal(h.calls.filter(call => call[0] === 'listMobileWaybillQueue').length - before, 1)
  } finally { h.stop() }
})
test('a tab change discards completion refresh and its focus target', async () => {
  const pending = deferred(); let refreshing = false
  const h = await harness({ listMobileWaybillQueue: async params => refreshing && params.tab === 'pending' ? pending.promise : ({ data: { items: [row], total: 1, has_more: false } }), createInspectionShipment: async () => { refreshing = true; return { data: {} } } })
  try {
    await h.state.loadQueue(); await h.state.begin(row); await h.state.captured(h.photo); await h.state.sync()
    const submission = h.state.submit(); await new Promise(resolve => setImmediate(resolve)); h.state.tab.value = 'done'; await vue.nextTick()
    pending.resolve({ data: { items: [{ ...row, id: 99 }], total: 1, has_more: false } }); await submission
    assert.equal(h.state.tab.value, 'done'); assert.equal(h.state.rows.value[0].id, 1); assert.equal(h.state.nextInspectionId.value, null)
  } finally { h.stop() }
})
test('finishing the last card leaves an empty queue without a focus target', async () => {
  let completed = false
  const h = await harness({ listMobileWaybillQueue: async () => ({ data: { items: completed ? [] : [row], total: completed ? 0 : 1, has_more: false } }), createInspectionShipment: async () => { completed = true; return { data: {} } } })
  try { await h.state.loadQueue(); await h.state.begin(row); await h.state.captured(h.photo); await h.state.sync(); await h.state.submit(); assert.equal(h.state.rows.value.length, 0); assert.equal(h.state.nextInspectionId.value, null) } finally { h.stop() }
})
