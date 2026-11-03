import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const modelUrl = new URL('./navigationEditor.js', import.meta.url).href
const original = await readFile(new URL('./useNavigationEditor.js', import.meta.url), 'utf8')
async function harness(api) {
  const globals = { api, ref: value => ({ value }), computed: getter => ({ get value() { return getter() } }), onBeforeUnmount() {}, onMounted() {}, onBeforeRouteLeave() {}, confirmAction: async () => true, isFeedbackCancelled: () => false, msgError() {}, msgSuccessText() {}, msgWarning() {}, promptAction: async () => ({ value: 'New' }) }
  const token = `navigationHarness${Math.random()}`
  globalThis[token] = globals
  const get = `globalThis[${JSON.stringify(token)}]`
  const source = original.replace(/import \{ computed[^\n]+from 'vue'/, `const { computed, onBeforeUnmount, onMounted, ref } = ${get}`)
    .replace(/import \{ onBeforeRouteLeave \} from 'vue-router'/, `const { onBeforeRouteLeave } = ${get}`)
    .replace(/import \* as api from '@\/api\/navigationConfig'/, `const api = ${get}.api`)
    .replace(/import \{ confirmAction[^\n]+from '@\/utils\/feedback'/, `const { confirmAction, isFeedbackCancelled, msgError, msgSuccessText, msgWarning, promptAction } = ${get}`)
    .replace("from './navigationEditor'", `from '${modelUrl}'`)
  const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
  const state = module.useNavigationEditor()
  delete globalThis[token]
  return state
}
const node = { id: 'home', kind: 'page', label: 'Home', icon: 'House', parent: '', order: 0, visible: true, badge: '', badgePlace: 'text', badgeTone: 'gold', titleSync: false }
function baseApi() {
 const envelope = data => Promise.resolve({ data })
 return { getNavigationCatalog: () => envelope({ nodes: [node], icons: ['House'], catalog_hash: 'hash' }), getNavigationDraft: () => envelope({ nodes: [node], draft_revision: 1, base_version: 0, catalog_hash: 'hash' }), getNavigationVersions: () => envelope({ items: [{ id: 0, version: 0, nodes: [node] }] }) }
}
test('publish timeout reuses idempotency key; restoring a new draft resets it', async () => {
 const requests = []
 const api = { ...baseApi(), publishNavigationDraft: async request => { requests.push(request); throw new Error('timeout') }, restoreNavigationVersion: async () => ({ data: { nodes: [{ ...node, label: 'Restored' }], draft_revision: 2, base_version: 0, catalog_hash: 'hash' } }) }
 const state = await harness(api)
 await state.load(); await state.publish(); await state.publish()
 assert.equal(requests[0].request_id, requests[1].request_id)
 await state.restore({ id: 0, version: 0 }); await state.publish()
 assert.notEqual(requests[2].request_id, requests[0].request_id)
 assert.equal(requests[2].draft_revision, 2)
})
test('409 keeps local edits and blocks further saves until explicit reload', async () => {
 let saves = 0
 const api = { ...baseApi(), saveNavigationDraft: async () => { saves++; throw { response: { status: 409 } } } }
 const state = await harness(api); await state.load()
 state.nodes.value[0].label = 'Local change'; await state.save(); await state.save()
 assert.equal(saves, 1); assert.equal(state.conflict.value, true)
 assert.equal(state.nodes.value[0].label, 'Local change'); assert.equal(state.dirty.value, true)
})

test('save timeout queries server and accepts matching advanced revision without a second write', async () => {
 let reads = 0, writes = 0, submitted
 const api = { ...baseApi(), getNavigationDraft: async () => { reads++; return { data: { nodes: reads === 1 ? [node] : submitted.nodes.toReversed(), draft_revision: reads === 1 ? 1 : 2, base_version: 0, catalog_hash: 'hash' } } }, saveNavigationDraft: async request => { writes++; submitted = request; throw new Error('timeout') } }
 const state = await harness(api); await state.load(); state.nodes.value[0].label = 'Saved rename'
 assert.equal(await state.save(), true); assert.equal(writes, 1); assert.equal(reads, 2)
 assert.equal(state.dirty.value, false); assert.equal(state.conflict.value, false)
})
test('save timeout with different remote content preserves local edits and blocks writes', async () => {
 let reads = 0, writes = 0
 const api = { ...baseApi(), getNavigationDraft: async () => ({ data: { nodes: [{ ...node, label: ++reads === 1 ? 'Home' : 'Other editor' }], draft_revision: reads === 1 ? 1 : 2, base_version: 0, catalog_hash: 'hash' } }), saveNavigationDraft: async () => { writes++; throw new Error('timeout') } }
 const state = await harness(api); await state.load(); state.nodes.value[0].label = 'Local'
 assert.equal(await state.save(), false); await state.save()
 assert.equal(writes, 1); assert.equal(state.conflict.value, true); assert.equal(state.nodes.value[0].label, 'Local')
})
test('failed reconciliation retries only the read and preserves newer local edits', async () => {
 let reads = 0, writes = 0, submitted
 const api = { ...baseApi(), getNavigationDraft: async () => { reads++; if (reads === 2) throw new Error('offline'); return { data: { nodes: reads === 1 ? [node] : submitted.nodes, draft_revision: reads === 1 ? 1 : 2, base_version: 0, catalog_hash: 'hash' } } }, saveNavigationDraft: async request => { writes++; submitted = request; throw new Error('timeout') } }
 const state = await harness(api); await state.load(); state.nodes.value[0].label = 'First local'
 assert.equal(await state.save(), false); assert.equal(state.dirty.value, true)
 state.nodes.value[0].label = 'Newer local'; assert.equal(await state.save(), false)
 assert.equal(writes, 1); assert.equal(reads, 3); assert.equal(state.conflict.value, true); assert.equal(state.nodes.value[0].label, 'Newer local')
})
