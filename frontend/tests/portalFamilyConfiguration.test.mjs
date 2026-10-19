import test from 'node:test'
import assert from 'node:assert/strict'
import { assignBody, familyBody, packHint, swatchBody } from '../src/views/portal/familyConfiguration.mjs'

const family = () => ({ display_name: 'K Tip', unit_weight_grams: '1', min_qty: 25, step_qty: 25, out_of_stock_below: '200',
  allowed_grades: ['super', 'standard'], sort_order: 40, status: 'enabled', reason: 'tune' })

test('family body keeps decimal text and canonical grade order', () => {
  const body = familyBody(family())
  assert.deepEqual(body.allowed_grades, ['standard', 'super'])
  assert.equal(body.unit_weight_grams, '1')
})

test('family body rejects invalid rules', () => {
  for (const change of [{ min_qty: 30 }, { unit_weight_grams: '0' }, { unit_weight_grams: '1e2' }, { allowed_grades: [] },
    { display_name: '<b>' }, { reason: ' ' }, { status: 'draft' }]) assert.throws(() => familyBody({ ...family(), ...change }))
})

test('assignment requires family and grade unless clearing', () => {
  const ids = ['a', 'a', 'b']
  assert.deepEqual(assignBody({ item_ids: ids, family_code: 'k_tip', grade: 'super', reason: 'x' }).item_ids, ['a', 'b'])
  assert.deepEqual(assignBody({ item_ids: ids, clear: true, family_code: 'k_tip', grade: 'super', reason: 'x' }),
    { item_ids: ['a', 'b'], family_code: null, grade: null, reason: 'x' })
  assert.throws(() => assignBody({ item_ids: ids, family_code: '', grade: 'super', reason: 'x' }))
  assert.throws(() => assignBody({ item_ids: [], family_code: 'k_tip', grade: 'super', reason: 'x' }))
})

test('swatch body encodes keep, remove and previewed image', () => {
  const base = { color_code: ' #2 ', display_name: '', status: 'enabled', reason: 'x' }
  assert.deepEqual(swatchBody({ ...base, image: 'keep' }), { color_code: '#2', display_name: null, status: 'enabled', reason: 'x', asset_id: null, keep_image: true })
  assert.equal(swatchBody({ ...base, image: 'remove' }).keep_image, false)
  assert.throws(() => swatchBody({ ...base, image: 'new', asset_id: '7', asset_reference: '' }))
  assert.equal(swatchBody({ ...base, image: 'new', asset_id: '7', asset_reference: '7:' + 'a'.repeat(43) }).asset_id, '7')
})

test('pack hint shows grams per quantity step', () => {
  assert.equal(packHint({ unit_weight_grams: '2.5', step_qty: 10, sale_unit: 'piece' }), '每步 10 piece ≈ 25 g')
})
