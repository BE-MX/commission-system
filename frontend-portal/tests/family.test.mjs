import test from 'node:test'
import assert from 'node:assert/strict'
import { colorGroups, formatGrams, gradeOptions, lengthOptions, mergeAvailability, resolveSelection, selectionWeight, stepQuantity, stockLabel } from '../src/state/family.mjs'
import { familyCode } from '../src/api/client.mjs'

const v = (id, grade, length, color, type, availability = 'available', price = '27.0000') => ({ item_id: id, grade,
  grade_label: grade === 'super' ? 'Super Double Drawn' : 'Standard Double Drawn', length, color_key: color,
  color_code: '#' + color, color_type: type, availability, unit_price: price, stock_display: '100+', min_order_qty: 1, step_qty: 1 })
const variants = [
  v('a', 'standard', '18', '2', 'solid', 'unavailable'), v('b', 'standard', '20', '2', 'solid'),
  v('c', 'super', '18', 'p2-8', 'piano'), v('d', 'super', '18', '2', 'solid'), v('e', 'super', '18', '9atp9a-613', 'balayage', 'unknown'),
]

test('options report availability without hiding unavailable choices', () => {
  assert.deepEqual(gradeOptions(variants).map(o => [o.value, o.available]), [['standard', true], ['super', true]])
  assert.deepEqual(lengthOptions(variants, 'standard'), [{ value: '18', available: false }, { value: '20', available: true }])
})

test('colors group by business color-type order', () => {
  assert.deepEqual(colorGroups(variants, 'super', '18').map(g => [g.type, g.colors.map(c => c.item_id)]),
    [['solid', ['d']], ['piano', ['c']], ['balayage', ['e']]])
})

test('selection keeps valid choices and falls back to available ones', () => {
  assert.equal(resolveSelection(variants).variant.item_id, 'b')
  assert.equal(resolveSelection(variants, { grade: 'super', length: '18', colorKey: 'p2-8' }).variant.item_id, 'c')
  assert.equal(resolveSelection(variants, { grade: 'standard', length: '18' }).variant.item_id, 'a')
  assert.equal(resolveSelection(variants, { grade: 'super', length: '24', colorKey: 'zzz' }).variant.item_id, 'd')
  assert.equal(resolveSelection([]).variant, null)
})

test('polling merges stock fields only for known items', () => {
  const merged = mergeAvailability(variants, [{ item_id: 'b', availability: 'unavailable', stock_display: null, inventory_observed_at: 'x' }, { item_id: 'zzz', availability: 'available' }])
  assert.equal(merged.length, variants.length)
  assert.deepEqual([merged[1].availability, merged[1].stock_display, merged[1].unit_price], ['unavailable', null, '27.0000'])
  assert.equal(stockLabel(merged[1]), 'Out of stock')
  assert.equal(stockLabel(variants[1]), '100+ in stock')
  assert.equal(stockLabel(variants[4]), 'Availability pending')
})

test('stepper stays on the minimum plus step grid', () => {
  assert.equal(stepQuantity(25, 25, 25, 1), 50)
  assert.equal(stepQuantity(25, 25, 25, -1), 25)
  assert.equal(stepQuantity(37, 25, 25, 1), 50)
  assert.equal(stepQuantity('', 10, 10, 1), 20)
  assert.equal(stepQuantity(9999, 25, 25, 1), 10000)
  assert.equal(stepQuantity(9990, 10, 10, 1), 10000)
  assert.equal(stepQuantity(10000, 30, 30, 1), 9990)
})

test('selection weight sums known lines and flags unknown ones', () => {
  assert.deepEqual(selectionWeight([{ unit_weight_grams: '2.5', quantity: 40 }, { unit_weight_grams: '50', quantity: 3 }]), { grams: 250, complete: true })
  assert.deepEqual(selectionWeight([{ quantity: 2 }, { unit_weight_grams: '1', quantity: 25 }]), { grams: 25, complete: false })
  assert.equal(formatGrams(250), '250 g')
  assert.equal(formatGrams(1250), '1.25 kg')
  assert.equal(formatGrams(null), '—')
})

test('family codes are validated before building URLs', () => {
  assert.equal(familyCode('k_tip'), 'k_tip')
  for (const bad of ['../x', 'K-Tip', '', null, 'a'.repeat(33)]) assert.throws(() => familyCode(bad))
})
