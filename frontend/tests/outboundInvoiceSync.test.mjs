import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'

const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundInvoiceSync.js', import.meta.url), 'utf8')
  .replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('ref', 'msgSuccessText', 'previewOutboundInvoiceSync', 'syncOutboundInvoice', `${source}; return useOutboundInvoiceSync`)
const row = {record_source:'okki', outbound_invoice_id:'77', outbound_record_id:'1'}
const preview = {version:'a'.repeat(64), changed:true, changes:[]}

test('preview makes no write; apply blocks double clicks and refreshes only on verified success', async () => {
  const calls = []; let release
  const pending = new Promise(resolve => { release = resolve })
  const api = factory(ref, msg => calls.push(msg), async () => ({data:preview}),
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
  const api = factory(ref, msg => calls.push(msg),
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

test('a pre-protocol task opens the dialog on the manual review entry instead of failing', async () => {
  const guidance = '历史出库任务缺少可信原发送记录，请由仓库或开票管理员在出库单「人工核对」中确认未生成'
  const api = factory(ref, () => assert.fail('unexpected success'),
    async () => { throw Object.assign(Error('conflict'), { response: { status: 409, data: { detail: guidance } } }) },
    async () => assert.fail('unexpected sync'))(async () => assert.fail('unexpected refresh'))
  await api.previewSync(row)
  assert.equal(api.syncVisible.value, true)
  assert.deepEqual(api.syncPreview.value, { recover: true, manual_review: true, message: guidance })
  assert.equal(api.syncingId.value, null)
})

test('manual review sends resolution and reason once, then returns to a fresh preview', async () => {
  const calls = []; let previews = 0
  const api = factory(ref, msg => calls.push(msg),
    async () => { previews += 1; return { data: previews === 1 ? { status: 'sync_uncertain', recover: true, message: 'check' } : preview } },
    async (...args) => {
      // Readback recovery cannot settle the uncertain original; only the review releases it.
      if (!args[5]) return { data: { status: 'sync_uncertain', repairable: false, message: 'needs review' } }
      calls.push(args); return { data: { status: 'sync_failed', requires_preview: true, message: 'released' } }
    },
  )(async () => calls.push('refresh'))
  await api.previewSync(row)
  assert.equal(api.syncPreview.value.status, 'sync_uncertain')
  api.reviewVisible.value = true
  const review = { resolution: 'confirm_not_created', reason: 'checked in OKKI, nothing changed' }
  const first = api.submitReview(review); await api.submitReview(review)
  await first
  assert.deepEqual(calls, [['1', null, false, false, false, review], 'released', 'refresh'])
  assert.equal(api.reviewVisible.value, false)
  assert.equal(api.reviewing.value, false)
  assert.deepEqual(api.syncPreview.value, preview)
})
