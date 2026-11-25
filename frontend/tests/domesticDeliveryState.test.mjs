import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, reactive, ref } from 'vue'
import { deliveryTotal, deliveryPayload, filterDeliveryRows, deliveryUnitPrice, deliveryFundingGap } from '../src/views/domestic/deliverySelection.js'

const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticDelivery.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  .replace('export function useDomesticDelivery', 'function useDomesticDelivery')

function harness(overrides = {}) {
  const env = { computed, reactive, ref, deliveryTotal, deliveryPayload, filterDeliveryRows, deliveryUnitPrice, msgWarning() {}, currentBeijingDate: () => '2026-11-24', newRequestId: () => 'test', ...overrides }
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

test('funding coverage compares only shipped batches against unallocated receipts and recharge', () => {
  assert.equal(deliveryFundingGap({ scope: 'customer', transit_unpaid_amount: 0, received_unpaid_amount: 0, unallocated_recharges: 0, unallocated_receipts: 0, transit_unpaid_amount: 24823, unallocated_recharges: 20000, unallocated_receipts: 4823, account_balance: -99999 }), 0)
  assert.equal(deliveryFundingGap({ scope: 'customer', transit_unpaid_amount: 0, received_unpaid_amount: 0, unallocated_recharges: 0, unallocated_receipts: 0, received_unpaid_amount: 24823, unallocated_recharges: 20000 }), 4823)
  assert.equal(deliveryFundingGap({ scope: 'customer', transit_unpaid_amount: 0, received_unpaid_amount: 0, unallocated_recharges: 0, unallocated_receipts: 0, transit_unpaid_amount: 24823, unallocated_recharges: 30000 }), -5177)
})

test('recharge allocation retains earlier allocations and submits cumulative values without creating receipt', async () => {
  const writes = []
  const state = harness({ allocateDomesticRecharge: async (...args) => writes.push(args), msgSuccessText() {},
    getShipmentCandidates: async () => ({ data: [] }), getCustomerDelivery: async () => ({ data: {} }) })
  state.visible.value = true
  state.customerId.value = 7
  state.summary.value = { scope: 'customer' }
  state.batches.value = [{ id: 1, unpaid_amount: 0 }, { id: 2, unpaid_amount: 100 }]
  const recharge = { id: 9, amount: 150, unallocated_amount: 100, allocations: [{ shipment_id: 1, amount: 50 }] }
  state.openReceipt(null, recharge, 'recharge')
  assert.equal(state.allocationBatches.value.length, 2)
  assert.equal(state.receipt.allocations[2], 0)
  state.setAllocation(state.batches.value[1], 40)
  assert.equal(state.allocationTotal.value, 40)
  await state.confirmReceipt()
  assert.deepEqual(writes, [[7, 9, [{ shipment_id: 2, amount: 40 }]]])
})

test('restricted scope and a changed customer cannot submit a stale funding dialog', async () => {
  let writes = 0
  const state = harness({ allocateDomesticRecharge: async () => writes++ })
  state.customerId.value = 7
  state.summary.value = { scope: 'own_orders' }
  state.openReceipt(null, { id: 9, unallocated_amount: 10, allocations: [] }, 'recharge')
  assert.equal(state.receipt.visible, false)
  state.summary.value = { scope: 'customer' }
  state.openReceipt(null, { id: 9, unallocated_amount: 10, allocations: [] }, 'recharge')
  state.customerId.value = 8
  await state.confirmReceipt()
  assert.equal(writes, 0)
})

test('Tang Lan actual figures show a 24823 surplus and ignore account and unshipped deductions', () => {
  assert.equal(deliveryFundingGap({ scope: 'customer', transit_unpaid_amount: 192580, received_unpaid_amount: 18399,
    unallocated_recharges: 235802, unallocated_receipts: 0, account_balance: -17535, unshipped_amount: 42468 }), -24823)
})

test('legacy, incomplete and own-order scopes do not infer funding coverage', () => {
  const summary = { scope: 'customer', transit_unpaid_amount: 10, received_unpaid_amount: 0, unallocated_recharges: 20, unallocated_receipts: 0 }
  assert.equal(deliveryFundingGap({ ...summary, legacy_shipped_items: 1 }), null)
  assert.equal(deliveryFundingGap({ ...summary, scope: 'own_orders' }), null)
  assert.equal(deliveryFundingGap({ ...summary, unallocated_recharges: undefined }), null)
  assert.equal(deliveryFundingGap({}), null)
})

test('own-order readback retains scoped receipts but drops customer recharge data', async () => {
  const ownReceipt = { id: 3, amount: 20, status: 'approved', unallocated_amount: 10 }
  const state = harness({ getShipmentCandidates: async () => ({ data: [] }), getCustomerDelivery: async () => ({ data: {
    scope: 'own_orders', receipts: [ownReceipt], recharges: [{ id: 99 }], summary: { unallocated_receipts: 10 } } }) })
  state.visible.value = true; state.customerId.value = 7
  await state.reload()
  assert.deepEqual(state.receipts.value, [ownReceipt])
  assert.deepEqual(state.recharges.value, [])
  assert.equal(state.summary.value.unallocated_receipts, 10)
  state.openReceipt(null, ownReceipt)
  assert.equal(state.receipt.visible, false)
})

test('more than 200 historical allocations send only the changed cumulative target and disallow empty saves', async () => {
  const writes = []
  const state = harness({ allocateDomesticRecharge: async (...args) => writes.push(args), msgSuccessText() {},
    getShipmentCandidates: async () => ({ data: [] }), getCustomerDelivery: async () => ({ data: { scope: 'customer' } }) })
  state.visible.value = true; state.customerId.value = 7; state.summary.value = { scope: 'customer' }
  state.batches.value = [{ id: 300, unpaid_amount: 50 }]
  const allocations = Array.from({ length: 250 }, (_, i) => ({ shipment_id: i + 1, amount: 1 }))
  allocations.push({ shipment_id: 300, amount: 10 })
  state.openReceipt(null, { id: 9, amount: 360, unallocated_amount: 100, allocations }, 'recharge')
  await state.confirmReceipt()
  assert.equal(writes.length, 0)
  state.setAllocation(state.batches.value[0], 30)
  assert.equal(state.allocationTotal.value, 20)
  await state.confirmReceipt()
  assert.deepEqual(writes, [[7, 9, [{ shipment_id: 300, amount: 30 }]]])
})

test('allocation shortcuts fill the outstanding amount and clear only draft changes', async () => {
  const writes = []
  const state = harness({ allocateDomesticRecharge: async (...args) => writes.push(args), msgSuccessText() {},
    getShipmentCandidates: async () => ({ data: [] }), getCustomerDelivery: async () => ({ data: { scope: 'customer' } }) })
  state.visible.value = true
  state.customerId.value = 7
  state.summary.value = { scope: 'customer' }
  const rows = [{ id: 1, unpaid_amount: 10.25 }, { id: 2, unpaid_amount: 6.40 }, { id: 3, unpaid_amount: 13 }]
  state.batches.value = rows
  state.openReceipt(null, { id: 9, amount: 22.50, unallocated_amount: 17.50, allocations: [{ shipment_id: 1, amount: 5 }] }, 'recharge')

  state.fillAllocation(rows[0])
  assert.equal(state.receipt.allocations[1], 15.25)
  state.fillAllocation(rows[1])
  assert.equal(state.receipt.allocations[2], 6.40)
  state.clearAllocation(2)
  assert.equal(state.receipt.allocations[2], 0)

  state.fillAllAllocations([rows[0], rows[2], rows[1]])
  assert.deepEqual({ ...state.receipt.allocations }, { 1: 15.25, 2: 0, 3: 7.25 })
  assert.equal(state.allocationRemaining.value, 0)
  state.clearAllAllocations()
  assert.deepEqual({ ...state.receipt.allocations }, { 1: 5, 2: 0, 3: 0 })
  await state.confirmReceipt()
  assert.deepEqual(writes, [])

  state.fillAllocation(rows[1])
  await state.confirmReceipt()
  assert.deepEqual(writes, [[7, 9, [{ shipment_id: 2, amount: 6.40 }]]])
})

test('bulk allocation respects the request limit and preserves manually entered amounts when topping up', () => {
  const state = harness()
  state.customerId.value = 7
  state.summary.value = { scope: 'customer' }
  const rows = Array.from({ length: 201 }, (_, index) => ({ id: index + 1, unpaid_amount: 0.30 }))
  state.batches.value = rows
  state.openReceipt(null, { id: 9, amount: 100, unallocated_amount: 100, allocations: [] }, 'recharge')
  state.setAllocation(rows[200], 0.10)
  state.fillAllAllocations(rows)
  assert.equal(state.allocationTotal.value, 60)
  assert.equal(state.allocationRemaining.value, 40)
  assert.equal(state.receipt.allocations[200], 0)
  assert.equal(state.receipt.allocations[201], 0.30)
})
