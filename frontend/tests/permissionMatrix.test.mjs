import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const matrixSource = readFileSync(
  new URL('../src/views/system/composables/usePermissionMatrix.js', import.meta.url),
  'utf8',
)

test('festival dashboard has a Chinese label in the order and logistics group', () => {
  assert.match(matrixSource, /festival:\s*'采购节看板'/)

  const documentGroup = matrixSource.match(
    /\{ label: '单据 · 订单与物流', prefixes: \[([\s\S]*?)\]\s*\}/,
  )?.[1]
  assert.ok(documentGroup, 'document permission group should exist')
  assert.match(documentGroup, /'festival'/)
})

test('navigation permission prefixes use their Chinese navigation titles', () => {
  assert.match(matrixSource, /expo_store:\s*'门店管理'/)
  assert.match(matrixSource, /card:\s*'名片管家'/)
  assert.match(matrixSource, /design_image:\s*'AI 生图工作台'/)
  assert.match(matrixSource, /customer_image:\s*'客户产品效果图'/)
  assert.match(matrixSource, /domestic:\s*'内贸订单'/)
})

test('customer image permissions stay in the design-facing marketing group', () => {
  const marketingGroup = matrixSource.match(
    /\{ label: '营销 · 展会与洞见', prefixes: \[([\s\S]*?)\]\s*\}/,
  )?.[1]
  assert.ok(marketingGroup)
  assert.match(marketingGroup, /'customer_image'/)
})
