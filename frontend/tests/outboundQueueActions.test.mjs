import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'
import { OUTBOUND_STATE_LABELS } from '../src/views/shipping/composables/outboundStates.js'

const source = readFileSync(new URL('../src/views/shipping/composables/useOutboundRecords.js', import.meta.url), 'utf8')
  .replace(/^import .*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('ref', 'useRoute', 'useListPage', 'getOutboundPrintData', 'downloadOutboundWord',
  'buildOutboundDoc', 'printDocHtml', 'downloadBlob', 'ElMessage', `${source}; return useOutboundRecords`)

test('local shortage and sync-wait records never invoke export APIs', async () => {
  let calls = 0
  const api = factory(ref, () => ({query:{}}), () => ({}), async () => { calls++; return {data:{}} },
    async () => { calls++; return {} }, () => '', () => {}, () => {}, {error:()=>{}})()
  for (const outbound_state of ['waiting_stock','running','awaiting_sync','uncertain']) {
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
