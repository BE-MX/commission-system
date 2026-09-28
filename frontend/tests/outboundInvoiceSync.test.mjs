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
    async (id, version, check, confirm) => { calls.push([id,version,check,confirm]); await pending; return {data:{status:'sync_done',message:'done'}} })(async () => calls.push('refresh'))
  await api.previewSync({...row,record_source:'ark_task'})
  assert.equal(api.syncVisible.value, false)
  await api.previewSync(row)
  assert.deepEqual(calls, [])
  const first = api.applySync(); await api.applySync()
  assert.equal(calls.length, 1)
  release(); await first
  assert.deepEqual(calls, [['1',preview.version,false,false], 'done', 'refresh'])
  assert.equal(api.syncVisible.value, false)
  assert.equal(api.syncingId.value, null)
})

test('network failure retries through readback repair and never claims success without verification', async () => {
  const calls = []
  const api = factory(ref, {success: () => assert.fail('unexpected success')}, async () => ({data:preview}),
    async (id, version, check, confirm, repair) => {
      calls.push(repair)
      if (!repair) throw Error('timeout')
      return {data:{status:'sync_uncertain',recover:true,message:'check'}}
    })(async () => assert.fail('unexpected refresh'))
  await api.previewSync(row); await api.applySync(); await api.applySync()
  assert.deepEqual(calls, [undefined,true])
  assert.equal(api.syncVisible.value, true)
  assert.equal(api.syncPreview.value.recover, true)
})

test('recovery on row click returns to preview when no accepted operation exists', async () => {
  let reads = 0; const calls = []
  const api = factory(ref, {}, async () => ({data:++reads === 1 ? {...preview,recover:true} : preview}),
    async (id, version, check, confirm, repair) => { calls.push(repair); return {data:{requires_preview:true}} })(async () => {})
  await api.previewSync(row)
  assert.deepEqual(calls,[true]); assert.equal(reads,2)
  assert.equal(api.syncPreview.value.recover, undefined)
})

test('one row click continues verified missing-row repairs until printing is available', async () => {
  const calls = []; let refreshes = 0
  const api = factory(ref, {success: msg => calls.push(msg)},
    async () => ({data:{...preview,recover:true,message:'pending'}}),
    async (id, version, check, confirm, repair) => {
      assert.equal(repair, true)
      calls.push(id)
      return {data:calls.length === 1
        ? {status:'sync_uncertain',repairable:true,message:'one repaired'}
        : {status:'sync_done',message:'done'}}
    })(async () => { refreshes += 1 })
  await api.previewSync(row)
  assert.deepEqual(calls, ['1','1','done'])
  assert.equal(refreshes, 1)
  assert.equal(api.syncVisible.value, false)
})

test('inspection preview sends explicit recheck confirmation only on the manual action', async () => {
  const calls = []
  const api = factory(ref, {success: () => {}}, async () => ({data:{...preview,requires_recheck:true,inspection_status:'draft'}}),
    async (...args) => { calls.push(args); return {data:{status:'sync_done',message:'done'}} })(async () => {})
  await api.previewSync(row)
  assert.deepEqual(calls, [])
  await api.applySync()
  assert.deepEqual(calls, [['1', preview.version, false, true]])
})

test('definitive conflict reloads the inspection preview instead of treating it as an uncertain send', async () => {
  let reads = 0
  const api = factory(ref, {}, async () => ({data:{...preview,version:String(++reads).padStart(64,'a')}}),
    async () => { throw {response:{status:409}} })(async () => {})
  await api.previewSync(row)
  await api.applySync()
  assert.equal(reads, 2)
  assert.equal(api.syncPreview.value.recover, undefined)
})
