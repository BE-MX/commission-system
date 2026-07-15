import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const priceConfig = readFileSync(
  new URL('../src/views/invoice/InvoicePriceConfig.vue', import.meta.url),
  'utf8',
)
const accessoryConfig = readFileSync(
  new URL('../src/views/invoice/components/AccessoryPriceConfig.vue', import.meta.url),
  'utf8',
)
const api = readFileSync(new URL('../src/api/invoice.js', import.meta.url), 'utf8')

test('price configuration separates hair and accessory prices without duplicating shared panels', () => {
  assert.match(priceConfig, /label="头发价格"/)
  assert.match(priceConfig, /label="配件价格"/)
  assert.match(priceConfig, /<AccessoryPriceConfig\s*\/>/)
  assert.equal((priceConfig.match(/label="色型映射"/g) || []).length, 1)
  assert.equal((priceConfig.match(/label="客户价格规则"/g) || []).length, 1)
})

test('accessory price table only exposes its supported identity and pricing fields', () => {
  assert.match(accessoryConfig, /Hair ExtensionsTools Fee/)
  assert.match(accessoryConfig, /label="Name"/)
  assert.match(accessoryConfig, /label="Model"/)
  assert.match(accessoryConfig, /label="Color"/)
  assert.match(accessoryConfig, /label="标准价"/)
  assert.match(accessoryConfig, /class="list-table"/)
  assert.match(accessoryConfig, /\bborder\b/)
  assert.doesNotMatch(accessoryConfig, /Length|Net Weight|展开选填列/)
  assert.doesNotMatch(accessoryConfig, /align="center"/)
})

test('accessory price list separates currency and update time with bounded columns', () => {
  assert.match(accessoryConfig, /label="Name"[^>]*min-width="180"[^>]*max-width="320"/)
  assert.match(accessoryConfig, /label="Model"[^>]*min-width="150"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="Color"[^>]*min-width="150"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="标准价"[^>]*min-width="110"[^>]*max-width="150"/)
  assert.match(accessoryConfig, /label="币种"[^>]*min-width="90"[^>]*max-width="110"/)
  assert.match(accessoryConfig, /label="更新时间"[^>]*min-width="170"[^>]*max-width="240"/)
  assert.match(accessoryConfig, /label="操作"[^>]*width="160"[^>]*fixed="right"/)
  assert.match(accessoryConfig, /formatDateTime\(row\.updated_at\)/)
  assert.match(accessoryConfig, /if \(!value\) return '—'/)
  assert.match(accessoryConfig, /Number\(row\.standard_price\)\.toFixed\(2\)/)
  assert.doesNotMatch(accessoryConfig, /row\.currency\s*}}\s*{{\s*formatPrice/)
})

test('accessory editor selects a real OKKI product and SKU and keeps its snapshot readonly', () => {
  assert.match(accessoryConfig, /remote-method="searchCandidates"/)
  assert.match(accessoryConfig, /product_id/)
  assert.match(accessoryConfig, /sku_id/)
  const priceInput = accessoryConfig.match(/<el-input-number[^>]*v-model="dialog\.form\.price"[^>]*>/s)?.[0]
  assert.ok(priceInput, 'standard price input should exist')
  assert.match(priceInput, /:precision="2"/)
  assert.match(priceInput, /:max="99999999\.99"/)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_name"[^>]*readonly/s)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_model"[^>]*readonly/s)
  assert.match(accessoryConfig, /<el-input[^>]*:model-value="dialog\.form\.accessory_color"[^>]*readonly/s)
})

test('invoice API exposes the complete accessory price lifecycle through the existing client', () => {
  assert.match(api, /export function searchAccessoryCandidates\(params\)/)
  assert.match(api, /request\.get\('\/price\/accessory-candidates'/)
  assert.match(api, /export function listAccessoryPrices\(params\)/)
  assert.match(api, /request\.get\('\/price\/accessories'/)
  assert.match(api, /export function saveAccessoryPrice\(data\)/)
  assert.match(api, /request\.post\('\/price\/accessories'/)
  assert.match(api, /export function deleteAccessoryPrice\(id\)/)
  assert.match(api, /request\.delete\(`\/price\/accessories\/\$\{id\}`\)/)
  assert.doesNotMatch(api, /axios\.create/)
})
