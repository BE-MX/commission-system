import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  applyQuoteChange,
  applyQuoteResult,
  buildCreateItems,
  buildDraftSubmitPayload,
  buildQuoteRequest,
  hasBlockingPrice,
  invalidateItemQuote,
  membershipPreview,
  membershipLevelLabel,
  quoteChangeReasonLabel,
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
  const item = { key: 'line-a', expectedQuote: expected, quoteStatus: 'priced' }
  const current = { ...expected, discount_price: '960.00', membership_level: 'supreme' }
  const newId = applyQuoteChange([item], [{ client_key: 'line-a', item_id: null, ...current }], () => 'new-request')
  assert.equal(newId, 'new-request')
  assert.equal(item.expectedQuote.discount_price, '960.00')
  assert.equal(item.quoteStatus, 'priced')
  assert.equal(quoteChangeReasonLabel('membership_changed'), '客户会员等级已变化')
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

test('页面契约：不手改会员/单价，报价与草稿 API 都传 body', async () => {
  const [customers, createPage, api] = await Promise.all([
    readFile(new URL('../src/views/domestic/DomesticCustomers.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/domestic/DomesticOrderCreate.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/api/domestic.js', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(customers, /v-model="dialog\.membership_level"/)
  assert.doesNotMatch(createPage, /v-model="item\.unit_price"/)
  assert.match(api, /post\('\/pricing\/quote', data\)/)
  assert.match(api, /post\(`\/orders\/\$\{id\}\/submit`, data\)/)
})
