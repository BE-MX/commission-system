import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('order intelligence exposes the four multidimensional filters', () => {
  const filters = read('../src/views/order_intelligence/components/OrderFilters.vue')
  for (const label of ['国家（大洲 / 国家）', '产品型号', '颜色', '订单来源渠道']) {
    assert.match(filters, new RegExp(label.replace(/[（）/]/g, '\\$&')))
  }
  assert.match(filters, /<el-cascader/)
  assert.match(filters, /multiple/)
})

test('query arrays use repeated keys accepted by FastAPI list parameters', () => {
  const api = read('../src/api/orderIntelligence.js')
  assert.match(api, /paramsSerializer: \{ indexes: null \}/)
  for (const endpoint of ['overview', 'countries', 'people', 'customers']) {
    assert.match(api, new RegExp(`/${endpoint}`))
  }
})

test('monthly charts separate new-sign/first-return from repeat orders/amount', () => {
  const customerTrend = read('../src/views/order_intelligence/components/OrderTrendChart.vue')
  const repeatTrend = read('../src/views/order_intelligence/components/RepeatPurchaseTrendChart.vue')
  assert.match(customerTrend, /新签客户/)
  assert.match(customerTrend, /首返客户/)
  assert.doesNotMatch(customerTrend, /复购客户/)
  assert.match(repeatTrend, /repeat_orders/)
  assert.match(repeatTrend, /repeat_amount_usd/)
  assert.match(repeatTrend, /复购订单数/)
  assert.match(repeatTrend, /复购金额/)
})

test('AI brief generation includes the active multidimensional filters', () => {
  const composable = read('../src/views/order_intelligence/composables/useOrderIntelligence.js')
  for (const field of ['countries: selectedCountries.value', 'models: filters.models', 'colors: filters.colors', 'sources: filters.sources']) {
    assert.match(composable, new RegExp(field.replace(/[.]/g, '\\.')))
  }
  assert.match(composable, /generateOrderAiBrief\(\{ \.\.\.baseParams\(\), focus \}\)/)
})

test('customer profiles expose segment dimensions, product distributions, and profile alerts', () => {
  const page = read('../src/views/order_intelligence/OrderIntelligence.vue')
  const composable = read('../src/views/order_intelligence/composables/useOrderIntelligence.js')
  for (const label of ['客户画像', '客户性质', '新签型号', '首返周期', '典型复购周期', '统计期畅销产品', '统计期颜色', '统计期幅度']) {
    assert.match(page, new RegExp(label))
  }
  assert.match(page, /到期提醒/)
  assert.match(page, /周期异常/)
  assert.match(composable, /getCustomerProfileAnalysis/)
})

test('country opportunity list shows first-return customers right after new-sign customers', () => {
  const page = read('../src/views/order_intelligence/OrderIntelligence.vue')
  assert.match(page, /label="新签客户" prop="new_sign_customers" min-width="104" \/>\s*<el-table-column label="首返客户" prop="first_return_customers"/)
})

test('metrics board adds first-return card after new-sign and hides risk/forecast cards', () => {
  const page = read('../src/views/order_intelligence/OrderIntelligence.vue')
  const metrics = page.match(/<section class="oi-metrics"[\s\S]*?<\/section>/)[0]
  assert.ok(metrics.includes('首返客户'))
  assert.ok(metrics.indexOf('新签客户') < metrics.indexOf('首返客户'))
  assert.doesNotMatch(metrics, /需行动客户|GMV 预测/)
})

test('salespersons see an explicit self-scope hint while team/user filters stay admin-only', () => {
  const filters = read('../src/views/order_intelligence/components/OrderFilters.vue')
  assert.match(filters, /v-if="options\.can_read_all"/)
  assert.match(filters, /v-if="!options\.can_read_all"[^>]*>数据范围：仅本人/)
})
