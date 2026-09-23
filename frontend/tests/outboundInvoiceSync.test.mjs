import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'

const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundInvoiceSync.js', import.meta.url), 'utf8')
  .replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('ref', 'ElMessage', 'previewOutboundInvoiceSync', 'syncOutboundInvoice', `${source}; return useOutboundInvoiceSync`)
const row = {record_source:'okki', outbound_invoice_id:'77', outbound_record_id:'1'}
const preview = {version:'a'.repeat(64), changed:true, changes:[]}

test('preview makes no write; apply blocks double clicks and refreshes only on verified success', async () => {
  const calls = []; let release
  const pending = new Promise(resolve => { release = resolve })
  const api = factory(ref, {success: msg => calls.push(msg)}, async () => ({data:preview}),
    async (id, version, check) => { calls.push([id,version,check]); await pending; return {data:{status:'sync_done',message:'done'}} })(async () => calls.push('refresh'))
  await api.previewSync({...row,record_source:'ark_task'})
  assert.equal(api.syncVisible.value, false)
  await api.previewSync(row)
  assert.deepEqual(calls, [])
  const first = api.applySync(); await api.applySync()
  assert.equal(calls.length, 1)
  release(); await first
  assert.deepEqual(calls, [['1',preview.version,false], 'done', 'refresh'])
  assert.equal(api.syncVisible.value, false)
  assert.equal(api.syncingId.value, null)
})

test('uncertain or network failure uses check-only and never claims success', async () => {
  const calls = []
  const api = factory(ref, {success: () => assert.fail('unexpected success')}, async () => ({data:preview}),
    async (id, version, check) => { calls.push(check); if (!check) throw Error('timeout'); return {data:{status:'sync_uncertain',recover:true,message:'check'}} })(async () => assert.fail('unexpected refresh'))
  await api.previewSync(row); await api.applySync(); await api.applySync()
  assert.deepEqual(calls, [false,true])
  assert.equal(api.syncVisible.value, true)
  assert.equal(api.syncPreview.value.recover, true)
})

test('check-only with no accepted operation returns to preview without a write', async () => {
  let reads = 0; const calls = []
  const api = factory(ref, {}, async () => ({data:++reads === 1 ? {...preview,recover:true} : preview}),
    async (id, version, check) => { calls.push(check); return {data:{requires_preview:true}} })(async () => {})
  await api.previewSync(row); await api.applySync()
  assert.deepEqual(calls,[true]); assert.equal(reads,2)
  assert.equal(api.syncPreview.value.recover, undefined)
})
