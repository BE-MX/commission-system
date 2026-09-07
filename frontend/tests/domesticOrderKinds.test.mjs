import test from 'node:test'
import assert from 'node:assert/strict'
import { buildProductionPayload, detailSectionsForKind, routeForOrder } from '../src/views/domestic/domesticOrderKinds.js'
import { validateItemAttributes, visibleAttributeFields } from '../src/views/domestic/domesticAttributeRules.js'
import { buildDraftSubmitPayload } from '../src/views/domestic/composables/domesticMemberPricing.js'
import { buildCardDoc } from '../src/views/domestic/print/printDocs.js'

test('production cap needs blank specifications but no hairstyle series', () => {
  const attrs = { product_type: 'cap', craft: '递旋', size: '59', length: '20厘米' }
  assert.equal(validateItemAttributes(attrs, 'production'), '')
  assert.match(validateItemAttributes(attrs), /发型系列/)
  assert.equal(visibleAttributeFields(attrs, 'production').includes('hair_style_series'), false)
  assert.match(validateItemAttributes({ ...attrs, length: '15厘米' }, 'production'), /发量/)
  assert.equal(validateItemAttributes({ product_type: 'piece', craft: '全递针9*14', length: '25厘米' }, 'production'), '')
})

test('production payload omits customer, pricing, sales dimensions and hairstyle remnants', () => {
  const body = buildProductionPayload({
    order_no: 'old', customer_id: 1, order_type: 'first', order_channel: 'wechat', order_date: '2026-09-07',
    items: [{ key: 'one', order_qty: 3, attrs: { product_type: 'cap', craft: '递旋', size: '59', length: '20厘米', hair_style_series: 'old' },
      specialPrice: 999, laborFee: 1, hairstyle: 'old', style_images: ['old.png'], color: '黑', color_images: [{ path: 'black.png' }], remark: '备货' }],
  })
  assert.deepEqual(Object.keys(body).sort(), ['items', 'order_date', 'order_kind', 'remark'])
  assert.deepEqual(body.items[0], {
    client_key: 'one', order_qty: 3, attrs: { product_type: 'cap', craft: '递旋', length: '20厘米', size: '59' },
    color: '黑', color_images: ['black.png'], remark: '备货', remark_images: [],
  })
  assert.deepEqual(detailSectionsForKind('production', ['hairstyle', 'color', 'style_requirement', 'remark'].map(key => ({ key }))).map(s => s.key), ['color', 'remark'])
})

test('six route combinations select the matching API route regardless of craft mapping', () => {
  const routes = Object.fromEntries(['production', 'normal', 'special'].map((kind, i) => [kind, {
    cap: { route_id: i * 2 + 1 }, piece: { route_id: i * 2 + 2 },
  }]))
  for (const product_type of ['cap', 'piece']) {
    const item = { attrs: { product_type, craft: '任意启用工艺' } }
    assert.deepEqual(routeForOrder(item, 'production', 'normal', routes), routes.production[product_type])
    assert.deepEqual(routeForOrder(item, 'business', 'normal', routes), routes.normal[product_type])
    assert.deepEqual(routeForOrder(item, 'business', 'special', routes), routes.special[product_type])
    assert.equal(routeForOrder(item, 'production', 'normal', {}), null)
  }
})

test('production draft submit excludes zero-price snapshots', () => {
  assert.deepEqual(buildDraftSubmitPayload({ order_kind: 'production', items: [{ id: 4, unit_price: 0 }] }, () => 'request-1'), {
    request_id: 'request-1', expected_quotes: [],
  })
})

test('production flow card shows internal storage purpose without sales or hairstyle fields', () => {
  const html = buildCardDoc({ card: { order_kind: 'production', domestic_no: 'DP20260907-001',
    item: { product_name: '头套', order_qty: 4, hairstyle: 'should not print', color: '黑色', steps: [] } } })
  assert.match(html, /生产订单流转卡/)
  assert.match(html, /截止入库/)
  assert.match(html, /黑色/)
  assert.doesNotMatch(html, /客户店名|客户订单号|订单类别|订单类型|订单渠道|should not print/)
})
