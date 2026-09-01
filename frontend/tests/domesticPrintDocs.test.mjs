import assert from 'node:assert/strict'
import test from 'node:test'

import { buildCardDoc } from '../src/views/domestic/print/printDocs.js'

function card(overrides = {}) {
  return {
    domestic_no: 'DO20260901-001',
    order_no: 'CUSTOMER-1',
    order_date: '2026-09-01',
    customer_name: '测试客户',
    order_category: 'special',
    order_category_label: '特单',
    order_type: 'first_order',
    order_type_label: '首单',
    order_channel: 'wechat',
    order_channel_label: '微信',
    qr_data: 'ARK-D:1:test',
    printed_at: '2026-09-01 10:00:00',
    item: { product_name: '头套', order_qty: 1, steps: [] },
    ...overrides,
  }
}

test('flow card shows all order dimensions and special badge follows category', () => {
  const html = buildCardDoc({ card: card() })

  assert.match(html, /订单类别<\/td><td>特单/)
  assert.match(html, /订单类型<\/td><td>首单/)
  assert.match(html, /订单渠道<\/td><td>微信/)
  assert.match(html, /special-badge">特单/)

  const normal = buildCardDoc({
    card: card({ order_category: 'normal', order_category_label: '普货', order_type_label: '特单' }),
  })
  assert.doesNotMatch(normal, /special-badge">特单/)
})
