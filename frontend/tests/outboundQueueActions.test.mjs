import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { useListPage } from '../src/composables/useListPage.js'
import { ref, watch } from 'vue'
import { OUTBOUND_STATE_LABELS, OUTBOUND_STATE_TAGS, outboundPendingHint } from '../src/views/shipping/composables/outboundStates.js'
import { formatBeijingDateTime } from '../src/utils/datetime.js'

const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundRecords.js', import.meta.url), 'utf8')
  .replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('ref', 'watch', 'useRoute', 'useListPage', 'getOutboundPrintData', 'downloadOutboundWord',
  'buildOutboundDoc', 'printDocHtml', 'downloadBlob', 'msgError', 'deleteOutboundRecord', 'confirmDanger', 'msgSuccess', `${source}; return useOutboundRecords`)

test('local shortage and sync-wait records never invoke export APIs', async () => {
  let calls = 0
  const api = factory(ref, watch, () => ({query:{}}), () => ({}), async () => { calls++; return {data:{}} },
    async () => { calls++; return {} }, () => '', () => {}, () => {}, ()=>{})()
  for (const outbound_state of ['waiting_stock','running','retrying','failed','awaiting_sync','uncertain']) {
    const row = {outbound_record_id:'task:1',outbound_state,can_print:false}
    await api.openPrint(row)
    await api.downloadWord(row)
  }
  assert.equal(calls, 0)
  await api.openPrint({outbound_record_id:'111',can_print:true})
  await api.downloadWord({outbound_record_id:'111',can_print:true})
  assert.equal(calls, 2)
  assert.equal(OUTBOUND_STATE_LABELS.waiting_stock, '部分库存不足')
})

test('retrying shows a safe next step and Beijing midnight even on another client timezone', () => {
  const previous = process.env.TZ
  process.env.TZ = 'America/Los_Angeles'
  try {
    assert.equal(OUTBOUND_STATE_LABELS.retrying, '重新生成中')
    assert.equal(OUTBOUND_STATE_TAGS.retrying, 'warning')
    assert.equal(outboundPendingHint('retrying'), '系统正在重新生成，请稍后刷新查看')
    assert.equal(outboundPendingHint('failed'), '请联系管理员核对')
    assert.equal(outboundPendingHint('uncertain'), '请联系管理员核对')
    assert.equal(formatBeijingDateTime('2026-10-09 00:05:00'), '2026-10-09 00:05:00')
  } finally {
    if (previous === undefined) delete process.env.TZ
    else process.env.TZ = previous
  }
})

function deletionApi({confirm = async () => {}, remove = async () => {}} = {}) {
  const events = []
  const list = useListPage(async () => { events.push('refresh'); return { items: [], total: 0 } }, { immediate: false })
  list.list.value = [{}]; list.page.value = 2
  const api = factory(ref, watch, () => ({query:{}}), () => list, null, null, null, null, null, ()=>{},
    async id => { events.push(`delete:${id}`); return remove() },
    async (...args) => { events.push('confirm'); return confirm(...args) }, () => events.push('success'))()
  return {api, list, events}
}
const row = {record_source: 'okki', outbound_invoice_id: '77', outbound_record_id: '123', outbound_no: 'TEST'}

test('delete confirms remote scope and refreshes previous page only after success', async () => {
  const {api, list, events} = deletionApi({confirm: async (action, name, text) => {
    assert.equal(name, 'TEST'); assert.match(text, /小满/); assert.match(text, /整张/)
  }})
  await api.deleteRecord(row)
  assert.deepEqual(events, ['confirm','delete:123','success','refresh','refresh'])
  assert.equal(list.page.value, 1)
  assert.equal(api.deletingId.value, null)
})

test('cancel, local task and missing OKKI identity never invoke deletion', async () => {
  const {api, events} = deletionApi({confirm: async () => { throw 'cancel' }})
  await api.deleteRecord({...row, record_source:'ark_task'})
  await api.deleteRecord({...row, outbound_invoice_id:null})
  await api.deleteRecord(row)
  assert.deepEqual(events, ['confirm'])
  assert.equal(api.deletingId.value, null)
})

test('failed deletion keeps row and page; confirmation in flight blocks double click', async () => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const {api, list, events} = deletionApi({confirm: () => pending, remove: async () => { throw Error('uncertain') }})
  const first = api.deleteRecord(row)
  await api.deleteRecord(row)
  assert.deepEqual(events, ['confirm'])
  release()
  await assert.rejects(first, /uncertain/)
  assert.deepEqual(events, ['confirm','delete:123'])
  assert.equal(list.page.value, 2)
  assert.equal(list.list.value.length, 1)
  assert.equal(api.deletingId.value, null)
})
