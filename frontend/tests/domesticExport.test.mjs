import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const apiSource = readFileSync(new URL('../src/api/domestic.js', import.meta.url), 'utf8')
const viewSource = readFileSync(
  new URL('../src/views/domestic/DomesticOrders.vue', import.meta.url),
  'utf8',
)
const composableSource = readFileSync(
  new URL('../src/views/domestic/composables/useDomesticOrders.js', import.meta.url),
  'utf8',
)

test('domestic order export downloads one xlsx through the registered client', () => {
  const methodSource = apiSource.match(
    /export function exportOrder\(orderId\) \{[\s\S]*?\n\}/,
  )?.[0]
  assert.ok(methodSource, 'exportOrder API wrapper should exist')

  const calls = []
  const domesticClient = {
    get(path, config) {
      calls.push({ path, config })
      return 'response'
    },
  }
  const exportOrder = new Function(
    'domesticClient',
    `${methodSource.replace('export ', '')}; return exportOrder`,
  )(domesticClient)

  assert.equal(exportOrder(17), 'response')
  assert.deepEqual(calls, [{ path: '/orders/17/export', config: { responseType: 'blob' } }])
  assert.match(viewSource, /left-icon="Download" @click="handleExport\(row\)">导出<\/GlassButton>/)
  assert.match(composableSource, /downloadBlob\(response\)/)
})
