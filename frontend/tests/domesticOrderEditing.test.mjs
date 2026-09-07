import test from 'node:test'
import assert from 'node:assert/strict'
import { orderHeaderForm, buildHeaderPatch, orderItemForm, buildItemPatch, itemEditDelta, itemPriceError } from '../src/views/domestic/domesticOrderEditing.js'

test('order header patch changes only edited fields and never resends customer or route category', () => {
  const detail = { order_kind: 'business', order_no: 'PO1', order_date: '2026-09-07', required_ship_date: '2026-09-10',
    order_type: 'first_order', order_channel: 'wechat', customer_id: 7, order_category: 'normal', remark: 'old' }
  const form = orderHeaderForm(detail)
  form.remark = 'new'
  form.customer_id = 8
  form.order_category = 'special'
  assert.deepEqual(buildHeaderPatch(detail, form), { remark: 'new' })
  form.remark = ''
  assert.deepEqual(buildHeaderPatch(detail, form), { remark: null })
})

test('production edits cannot send sales prices or hairstyle fields', () => {
  const detail = { order_kind: 'production', order_date: '2026-09-07' }
  const form = { ...orderHeaderForm(detail), order_no: 'bad', order_type: 'first_order', remark: '备货' }
  assert.deepEqual(buildHeaderPatch(detail, form), { remark: '备货' })
  const item = { order_qty: 1, unit_price: 0 }
  const itemForm = { ...orderItemForm(item), order_qty: 2, unit_price: 900, hairstyle: 'bad', color: '黑色' }
  assert.deepEqual(buildItemPatch(detail, item, itemForm), { order_qty: 2, color: '黑色' })
})

test('editing one image list preserves other concurrent fields and the original object', () => {
  const item = { order_qty: 2, unit_price: 999.99, hairstyle_images: ['first.png'], color: '原色' }
  const form = orderItemForm(item)
  form.hairstyle_images.push('second.png')
  assert.deepEqual(item.hairstyle_images, ['first.png'])
  assert.deepEqual(buildItemPatch({}, item, form), { hairstyle_images: ['first.png', 'second.png'] })
  assert.equal(itemEditDelta(item, { ...form, unit_price: 999.98 }), -0.02)
  assert.equal(itemEditDelta(item, { ...form, order_qty: 3 }), 999.99)
})

test('legacy zero-price rows allow non-price edits while changed prices respect labor and original price', () => {
  const item = { order_qty: 1, original_price: 0, unit_price: 0, labor_fee: 0 }
  const form = { ...orderItemForm(item), remark: '补充要求', hairstyle_images: ['reference.png'], order_qty: 2 }
  const patch = buildItemPatch({ order_kind: 'business' }, item, form)
  assert.equal(itemPriceError(item, patch), '')
  assert.equal(Object.hasOwn(patch, 'unit_price'), false)
  assert.ok(itemPriceError(item, { unit_price: 1 }))
  const priced = { original_price: 1000, labor_fee: 30 }
  assert.ok(itemPriceError(priced, { unit_price: 30 }))
  assert.ok(itemPriceError(priced, { unit_price: 1030.01 }))
  assert.equal(itemPriceError(priced, { unit_price: 1030 }), '')
  assert.equal(itemPriceError({ original_price: 1000, labor_fee: 30.13 }, { unit_price: 1030.13 }), '')
  assert.ok(itemPriceError({ original_price: 1000, labor_fee: 30.13 }, { unit_price: 1030.14 }))
})
