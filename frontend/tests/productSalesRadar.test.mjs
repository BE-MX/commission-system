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

test('deep link keys match what the decision desk reads (including KeepAlive updates)', () => {
  const radar = read('../src/views/product_sales/ProductRadar.vue')
  const desk = read('../src/views/order_intelligence/composables/useOrderIntelligence.js')
  assert.match(radar, /path: '\/invoice\/order-intelligence', query: \{ tab: 'customers', \.\.\.\(color \? \{ colors: color \} : \{\}\), models: linkModels\.value/)
  assert.match(radar, /MAX_LINK_MODELS = 20/)
  assert.match(desk, /slice\(0, 20\)/)
  assert.match(desk, /export function applyRouteQuery/)
  for (const key of ['query.tab', 'query.models', 'query.colors']) assert.ok(desk.includes(key))
  // 深链预置的筛选不能写进「重置」基线
  assert.ok(desk.indexOf('const initialFilters = copy(filters)') < desk.indexOf('applyRouteQuery(useRoute()'))
  // KeepAlive 复用时再次从风向标跳入需同步 query 并重新分析
  assert.match(desk, /watch\(\(\) => route\.fullPath/)
  assert.match(desk, /deepLinkSignature\(route\.query\)/)
})

test('stale drawer and AI requests cannot overwrite the current view', () => {
  const state = read('../src/views/product_sales/composables/useProductRadar.js')
  assert.match(state, /const seq = \+\+detailSeq/)
  for (const guard of ['if (seq === detailSeq) detail.data', 'if (seq === detailSeq) detail.error']) assert.ok(state.includes(guard), guard)
  assert.match(state, /seq === insightSeq && target\.grade === radar\.value\?\.grade/)
  assert.match(state, /grade: radar\.value\.grade, window: radar\.value\.window\.days, \.\.\.row\.values/)
  assert.match(state, /if \(switched && !insight\.loading\)/)
  // 切换大类或窗口时旧内容保留（淡出），不整页清空；加载期间禁止点行和生成分析
  assert.match(state, /function switchScope\(\)[\s\S]*?\n  \}/)
  assert.doesNotMatch(state.match(/function switchScope\(\)[\s\S]*?\n  \}/)[0], /radar\.value = null/)
  assert.match(state, /async function openItem\(row[\s\S]*?if \(loading\.value \|\| !radar\.value\) return/)
  assert.match(state, /async function explain\(\) \{\n    if \(loading\.value \|\| !radar\.value\) return/)
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

test('P0/P1 UX & Apple motion contracts hold across radar, drawer and mappings', () => {
  const radar = read('../src/views/product_sales/ProductRadar.vue')
  const state = read('../src/views/product_sales/composables/useProductRadar.js')
  const drawer = read('../src/views/product_sales/components/RadarDetailDrawer.vue')
  const mappings = read('../src/views/product_sales/NameMappings.vue')
  const sharedDrawer = read('../src/components/DetailDrawer.vue')

  // 0 销量不能误标为「新出现」
  assert.match(state, /export function isNewAppearance\(row\)/)
  assert.match(radar, /isNewAppearance\(row\) \? '新出现' : '—'/)
  // 份额合并为单控件，且切视角仅淡化下方数据区
  assert.match(state, /scopeKey: ''/)
  assert.match(radar, /is-scope-busy/)
  assert.match(radar, /is-view-busy/)
  // 宽列表行不使用 scale 缩放塌陷
  assert.doesNotMatch(radar, /\.mover-row:active\s*\{[^}]*scale\(/)
  // 抽屉渲染 partial 未满月，使用 GPU scaleY transition 且支持下钻与按规格跳转
  assert.match(drawer, /is-partial/)
  assert.match(drawer, /days_covered/)
  assert.match(drawer, /scaleY\(var\(--ratio, 0\)\)/)
  assert.doesNotMatch(drawer, /@keyframes bar-grow/)
  assert.match(drawer, /\$emit\('drill-down'/)
  assert.match(drawer, /\$emit\('pivot-spec'\)/)
  // 公共抽屉使用苹果曲线
  assert.match(sharedDrawer, /--ease-drawer/)
  // 品名映射自动刷新可信度且带路由离开拦截
  assert.match(mappings, /onBeforeRouteLeave/)
  assert.match(mappings, /beforeunload/)
  assert.doesNotMatch(mappings, /映射已变更，重新计算/)
})
