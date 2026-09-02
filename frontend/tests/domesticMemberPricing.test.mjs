import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  applyQuoteChange,
  applyQuoteResult,
  buildCreateItems,
  buildDraftSubmitPayload,
  buildQuoteRequest,
  effectiveDiscountPrice,
  hasBlockingPrice,
  invalidateItemQuote,
  membershipPreview,
  membershipLevelLabel,
  membershipChangeLabel,
  ensureRequestIdentity,
  priceImpactLabel,
  quoteChangeRows,
  quoteChangeReasonLabel,
  pricingRuleLabelForQuote,
} from '../src/views/domestic/composables/domesticMemberPricing.js'

const attrs = { product_type: 'cap', craft: '递旋', net_color: '', size: '', length: '15厘米', density: '', hair_style_series: '' }
const expected = {
  original_price: '1198.00', base_price_version: 2, discount_price: '998.00',
  membership_level: 'black', pricing_rule: 'member_fixed', pricing_version: '2026-09-01',
}

test('会员预览只由本次充值金额决定，边界正确', () => {
  assert.deepEqual([9999.99, 10000, 29999.99, 30000, 99999.99, 100000].map(membershipPreview), [
    '普通客户', '银卡会员', '银卡会员', '黑卡会员', '黑卡会员', '至尊会员',
  ])
  assert.equal(membershipLevelLabel('black'), '黑卡会员')
  assert.equal(membershipLevelLabel(null), '非会员')
})

test('报价请求用稳定 client_key 与当前属性', () => {
  const form = { customer_id: 7, items: [{ key: 'line-a', attrs }] }
  assert.deepEqual(buildQuoteRequest(form, value => value), {
    customer_id: 7, items: [{ client_key: 'line-a', attrs }],
  })
})

test('报价回填与属性变化失效不会丢 client_key', () => {
  const item = { key: 'line-a', quoteStatus: 'pending', expectedQuote: null }
  applyQuoteResult([item], { items: [{ client_key: 'line-a', status: 'priced', original_price: '1198.00', discount_price: '998.00', discount_amount: '200.00', pricing_rule_label: '黑卡会员价', expected_quote: expected }] })
  assert.equal(item.quoteStatus, 'priced')
  assert.deepEqual(item.expectedQuote, expected)
  invalidateItemQuote(item)
  assert.equal(item.quoteStatus, 'pending')
  assert.equal(item.expectedQuote, null)
  assert.equal(item.key, 'line-a')
})

test('缺原价阻断，建单 payload 不再发 unit_price', () => {
  const missing = { key: 'm', attrs, order_qty: 1, quoteStatus: 'missing_base_price' }
  assert.equal(hasBlockingPrice([missing]), true)
  const priced = { key: 'p', attrs, order_qty: 2, expectedQuote: expected, hairstyle_images: [], color_images: [], style_images: [], remark_images: [] }
  const [payload] = buildCreateItems([priced], value => value)
  assert.equal(payload.client_key, 'p')
  assert.deepEqual(payload.expected_quote, expected)
  assert.equal('unit_price' in payload, false)
})

test('409 必须替换报价并生成新幂等键', () => {
  const item = { key: 'line-a', expectedQuote: expected, quoteStatus: 'priced', quote: { pricing_rule_label: '旧规则文案' } }
  const current = { ...expected, discount_price: '960.00', membership_level: 'supreme' }
  const newId = applyQuoteChange([item], [{ client_key: 'line-a', item_id: null, ...current }], () => 'new-request')
  assert.equal(newId, 'new-request')
  assert.equal(item.expectedQuote.discount_price, '960.00')
  assert.equal(item.quoteStatus, 'priced')
  assert.equal(item.quote.pricing_rule_label, '至尊会员固定会员价')
  assert.notEqual(item.quote.pricing_rule_label, '旧规则文案')
  assert.equal(quoteChangeReasonLabel('membership_changed'), '客户会员等级已变化')
})

test('409 变化摘要同时展示原价、优惠价和规则，价格相同也不隐藏', () => {
  const rows = quoteChangeRows({ changes: [{
    client_key: 'line-a', reasons: ['membership_changed'],
    previous_quote: expected,
    current_quote: { ...expected, membership_level: 'supreme', pricing_rule: 'member_fixed_capped' },
  }] }, key => key === 'line-a' ? '第 2 行' : key)
  assert.equal(rows.length, 1)
  assert.match(rows[0], /原价 ¥1198\.00 → ¥1198\.00/)
  assert.match(rows[0], /优惠价 ¥998\.00 → ¥998\.00/)
  assert.match(rows[0], /规则 黑卡会员固定会员价 → 命中固定会员价，但原价更低，已按原价/)
  assert.equal(pricingRuleLabelForQuote({ ...expected, pricing_rule: 'member_reduction', discount_price: '1078.00' }), '黑卡会员立减 ¥120.00')
})

test('建单幂等键按 payload 指纹管理', () => {
  let serial = 0
  const factory = () => `request-${++serial}`
  const payload = { customer_id: 7, order_no: 'A1', items: [{ attrs, order_qty: 1 }] }
  const first = ensureRequestIdentity(null, payload, factory)
  const retry = ensureRequestIdentity(first, structuredClone(payload), factory)
  const changed = ensureRequestIdentity(retry, { ...payload, customer_id: 8 }, factory)
  assert.equal(first.requestId, 'request-1')
  assert.equal(retry.requestId, 'request-1')
  assert.equal(changed.requestId, 'request-2')
})

test('会员变化和共享原价预检文案是业务可读的', () => {
  assert.equal(membershipChangeLabel({ from: 'silver', to: 'black' }), '银卡会员 → 黑卡会员')
  assert.equal(membershipChangeLabel(null), '')
  assert.equal(priceImpactLabel({
    price_key: { product_type: 'piece', craft: '全递针13*15', length: '35cm' }, affected_sku_count: 4,
  }), '发片 / 全递针13*15 / 35cm，共影响 4 个 SKU')
})

test('草稿提交 body 直接回传 item_id 报价快照', () => {
  const quotes = [{ item_id: 12, client_key: null, ...expected }]
  assert.deepEqual(buildDraftSubmitPayload({ current_expected_quotes: quotes }, () => 'draft-request'), {
    request_id: 'draft-request', expected_quotes: quotes,
  })
  assert.deepEqual(buildDraftSubmitPayload({ items: [{
    id: 12, original_price: '1198.00', base_price_version: 2, unit_price: '998.00',
    membership_level_snapshot: 'black', pricing_rule: 'member_fixed', pricing_version: '2026-09-01',
  }] }, () => 'fallback-request'), {
    request_id: 'fallback-request', expected_quotes: [{ item_id: 12, client_key: null, ...expected }],
  })
})

test('手工改价进入建单 payload，失效与恢复都回到系统报价', () => {
  const item = {
    key: 'line-a', attrs, order_qty: 2, expectedQuote: expected,
    quoteStatus: 'priced', manualDiscountPrice: 950,
    quote: { status: 'priced', original_price: '1198.00', discount_price: '998.00' },
    hairstyle_images: [], color_images: [], style_images: [], remark_images: [],
  }
  assert.equal(effectiveDiscountPrice(item), 950)
  const [payload] = buildCreateItems([item], value => value)
  assert.equal(payload.manual_discount_price, 950)
  assert.equal('unit_price' in payload, false)

  // 等于系统报价或清空都不发手工价
  item.manualDiscountPrice = null
  assert.equal(effectiveDiscountPrice(item), 998)
  assert.equal(buildCreateItems([item], value => value)[0].manual_discount_price, null)

  // 属性变化让报价失效时手工价一并清掉
  item.manualDiscountPrice = 950
  invalidateItemQuote(item)
  assert.equal(item.manualDiscountPrice, null)

  // 重新报价后原价下调到手工价之下：恢复系统报价并报告清掉的行
  item.quoteStatus = 'pending'
  item.manualDiscountPrice = 950
  const cleared = applyQuoteResult([item], { items: [{
    client_key: 'line-a', status: 'priced',
    original_price: '900.00', discount_price: '880.00',
    expected_quote: { ...expected, original_price: '900.00', discount_price: '880.00' },
  }] })
  assert.deepEqual(cleared, ['line-a'])
  assert.equal(item.manualDiscountPrice, null)
  assert.equal(effectiveDiscountPrice(item), 880)

  assert.equal(pricingRuleLabelForQuote({ pricing_rule: 'manual_override' }), '手工改价')
  assert.equal(pricingRuleLabelForQuote({ pricing_rule: 'legacy_manual' }), '历史手工价')
})

test('页面契约：不手改会员，优惠价只能走手工改价契约', async () => {
  const [customers, createPage, createLogic, orders, products, api] = await Promise.all([
    readFile(new URL('../src/views/domestic/DomesticCustomers.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/domestic/DomesticOrderCreate.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/domestic/composables/useDomesticOrderCreate.js', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/domestic/DomesticOrders.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/domestic/DomesticProducts.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/api/domestic.js', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(customers, /v-model="dialog\.membership_level"/)
  assert.match(customers, /openInit/)
  assert.match(customers, /openAdjust/)
  assert.match(customers, /__keep__/)
  assert.match(api, /post\(`\/customers\/\$\{id\}\/initialize`, data\)/)
  assert.match(api, /post\(`\/customers\/\$\{id\}\/adjust`, data\)/)
  assert.doesNotMatch(createPage, /v-model="item\.unit_price"/)
  assert.match(api, /post\('\/pricing\/quote', data\)/)
  assert.match(api, /post\(`\/orders\/\$\{id\}\/submit`, data/)
  assert.match(api, /base-price-impact/)
  assert.match(api, /put\(`\/items\/\$\{itemId\}`, data\)/)
  assert.match(createLogic, /quoteLoading\.value = false/)
  assert.match(createLogic, /name: 'DomesticProducts'/)
  assert.match(createPage, /goProducts/)
  assert.match(createPage, /onManualPrice/)
  assert.match(orders, /submittingOrderIds\.has\(row\.id\)/)
  assert.match(orders, /openPriceEdit/)
  assert.match(products, /affected_sku_count/)
})
