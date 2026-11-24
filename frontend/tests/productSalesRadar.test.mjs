import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('product radar and mapping pages are registered with their permissions', () => {
  const nav = read('../src/config/navigation.js')
  assert.match(nav, /path: '\/customer-hub\/product-radar'[\s\S]*?permission: 'product_sales:read'/)
  assert.match(nav, /path: '\/stock\/product-name-mappings'[\s\S]*?permission: 'product_sales:admin'/)
})

test('radar list parameters use repeated keys accepted by FastAPI', () => {
  const api = read('../src/api/productSales.js')
  assert.match(api, /paramsSerializer: \{ indexes: null \}/)
  for (const endpoint of ['/radar', '/radar/item', '/radar/scopes', '/radar/insight']) assert.ok(api.includes(`'${endpoint}'`))
})

test('deep link keys match what the decision desk reads', () => {
  const radar = read('../src/views/product_sales/ProductRadar.vue')
  const desk = read('../src/views/order_intelligence/composables/useOrderIntelligence.js')
  assert.match(radar, /path: '\/invoice\/order-intelligence', query: \{ tab: 'customers', \.\.\.\(color \? \{ colors: color \} : \{\}\), models: linkModels\.value/)
  assert.match(radar, /MAX_LINK_MODELS = 20/)
  assert.match(desk, /slice\(0, 20\)/)
  assert.match(desk, /export function applyRouteQuery/)
  for (const key of ['query.tab', 'query.models', 'query.colors']) assert.ok(desk.includes(key))
  // 深链预置的筛选不能写进「重置」基线
  assert.ok(desk.indexOf('const initialFilters = copy(filters)') < desk.indexOf('applyRouteQuery(useRoute()'))
})

test('stale drawer and AI requests cannot overwrite the current view', () => {
  const state = read('../src/views/product_sales/composables/useProductRadar.js')
  assert.match(state, /const seq = \+\+detailSeq/)
  for (const guard of ['if (seq === detailSeq) detail.data', 'if (seq === detailSeq) detail.error']) assert.ok(state.includes(guard), guard)
  assert.match(state, /seq === insightSeq && target\.grade === radar\.value\?\.grade/)
  assert.match(state, /grade: radar\.value\.grade, window: radar\.value\.window\.days, \.\.\.row\.values/)
  assert.match(state, /if \(switched && !insight\.loading\)/)
  assert.match(state, /function switchScope\(\)[\s\S]*?radar\.value = null/)
  assert.match(state, /const refresh = !!insight\.data/)
})

test('grade tabs, windows and dimension views match the backend contract', () => {
  const state = read('../src/views/product_sales/composables/useProductRadar.js')
  assert.match(state, /\[30, 60, 90, 180\]/)
  for (const grade of ["value: 'B1'", "value: 'B3'", "value: '50'"]) assert.ok(state.includes(grade), grade)
  for (const dim of ["'spec'", "'color'", "'size'"]) assert.ok(state.includes(dim), dim)
  const radar = read('../src/views/product_sales/ProductRadar.vue')
  assert.match(radar, /DOMPurify\.sanitize\(marked\.parse/)
})

test('customer link is hidden without decision desk permission', () => {
  const radar = read('../src/views/product_sales/ProductRadar.vue')
  assert.match(radar, /hasPermission\('order_intelligence:read'\)/)
})
