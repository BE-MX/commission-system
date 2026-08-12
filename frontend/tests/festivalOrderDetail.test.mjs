import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('festival order detail is a permission-gated order-management page', () => {
  const navigation = read('../src/config/navigation.js')
  const api = read('../src/api/festivalOrder.js')
  const clients = read('../src/api/clients.js')
  assert.match(navigation, /path: '\/invoice\/festival-orders'/)
  assert.match(navigation, /const FESTIVAL_ORDER_PERMISSION = 'festival_order:read'/)
  assert.match(navigation, /permission: FESTIVAL_ORDER_PERMISSION/)
  assert.match(navigation, /title: '采购节数据明细'/)
  assert.match(api, /import { festivalClient } from '\.\/clients'/)
  assert.match(clients, /export const festivalClient = createApiClient/)
})

test('page exposes confirmed metrics, three tabs, and required order columns', () => {
  const view = read('../src/views/invoice/FestivalOrderDetail.vue')
  for (const text of ['新签完成进度', '首返客户数', '复购金额', '新签订单', '首返订单', '复购订单']) {
    assert.match(view, new RegExp(text))
  }
  for (const prop of ['order_no', 'account_date', 'amount_usd', 'company_name', 'user_name', 'team', 'camp']) {
    assert.match(view, new RegExp(`prop="${prop}"`))
  }
  assert.match(view, /v-if="summary\.can_read_all"/)
})

test('data loader keeps successful data when a later request fails', () => {
  const composable = read('../src/views/invoice/composables/useFestivalOrderDetail.js')
  assert.match(composable, /Promise\.all\(\[getFestivalOrderSummary/)
  assert.match(composable, /summary\.value = nextSummary/)
  assert.match(composable, /orders\.value = nextPage\.items \|\| \[\]/)
  assert.match(composable, /if \(requestId !== latestRequest\) return/)
  assert.doesNotMatch(composable, /catch[\s\S]{0,180}(summary\.value\s*=|orders\.value\s*=\s*\[\])/)
})

test('high-frequency tabs do not use transform animations', () => {
  const view = read('../src/views/invoice/FestivalOrderDetail.vue')
  const styles = read('../src/views/invoice/festival-order-detail.css')
  const tabsBlock = styles.match(/\.festival-tabs[\s\S]*?(?=\n\.[a-z]|\n@media|$)/)?.[0] || ''
  assert.doesNotMatch(tabsBlock, /transform|animation/)
  assert.equal((view.match(/lg-card is-static/g) || []).length, 3)
})
