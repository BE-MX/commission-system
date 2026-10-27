import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { loadOrderUnitLabels } from '../src/views/domestic/print/orderUnitLabels.js'
const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticOrderSkip.js', import.meta.url), 'utf8')
function setup(prompt, write) {
  const calls = []
  const factory = new Function('ref', 'promptAction', 'msgSuccessText', 'skipAllOrderProcesses', 'newRequestId', source.replace(/^import .*$/gm, '').replace('export function', 'function') + '\nreturn useDomesticOrderSkip')
  let key = 0
  const state = factory(value => ({ value }), prompt, () => {}, async (...args) => { calls.push(args); await write?.() }, () => `request-${++key}`)(async () => calls.push('refresh'))
  return { ...state, calls }
}
test('skip cancel writes nothing and uncertain retry preserves confirmed scope and request', async () => {
  const cancel = setup(async () => { throw new Error('cancel') })
  await cancel.handleSkipAll({ id: 1 })
  assert.equal(cancel.calls.length, 0)
  let fail = true, prompts = 0
  const ui = setup(async () => { prompts++; return { value: '  主管确认无需加工  ' } }, async () => { if (fail) throw new Error('network') })
  await assert.rejects(ui.handleSkipAll({ id: 1 }))
  fail = false
  await ui.handleSkipAll({ id: 1 })
  assert.deepEqual(ui.calls[0], ui.calls[1])
  assert.equal(prompts, 1)
  assert.equal(ui.skippingAll.value, false)
})
test('whole order prints sparse surviving identities beyond current quantity', async () => {
  const calls = []
  const result = await loadOrderUnitLabels({ items: [{ id: 1, order_qty: 2, max_unit_no: 205 }] }, async (id, range) => {
    calls.push(range)
    return { data: { order_qty: 2, max_unit_no: 205, units: (range.start_no === 1 ? [1] : [205]).map(unit_no => ({ unit_no })) } }
  })
  assert.equal(calls[1].end_no, 205)
  assert.deepEqual(result.groups.flatMap(g => g.units.map(u => u.unit_no)), [1, 205])
})
