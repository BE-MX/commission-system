import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, reactive, ref } from 'vue'
import { deliveryTotal, deliveryPayload, filterDeliveryRows, deliveryUnitPrice } from '../src/views/domestic/deliverySelection.js'

const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticDelivery.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  .replace('export function useDomesticDelivery', 'function useDomesticDelivery')

function harness() {
  const env = { computed, reactive, ref, deliveryTotal, deliveryPayload, filterDeliveryRows, deliveryUnitPrice, msgWarning() {} }
  return new Function(...Object.keys(env), `${source}; return useDomesticDelivery`)(...Object.values(env))(() => {})
}

test('batch override survives quantity and explicit-unit edits; deselection resets it', () => {
  const state = harness()
  const row = { item_id: 1, unit_price: 100, available_qty: 3, units: [{ id: 1 }, { id: 2 }, { id: 3 }] }
  state.candidates.value = [row]
  state.toggle(row, true)
  state.setUnitPrice(row, '80.25')
  state.setQuantity(row, 2)
  assert.equal(state.selected[1].unit_price, '80.25')
  state.openUnits(row)
  state.units.selected = [3]
  state.confirmUnits()
  assert.equal(state.selected[1].unit_price, '80.25')
  assert.deepEqual(deliveryPayload([row], state.selected), [{ item_id: 1, quantity: 1, unit_ids: [3], unit_price: 80.25 }])
  state.setUnitPrice(row, '0')
  assert.equal(state.totals.value.cents, 0)
  state.toggle(row, false)
  state.toggle(row, true)
  assert.equal(state.batchUnitPrice(row), 100)
  assert.equal(row.unit_price, 100)
})
