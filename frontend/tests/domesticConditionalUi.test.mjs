import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'


const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')


test('domestic API exposes route-rule and audited skip operations', () => {
  const api = read('../src/api/domestic.js')

  assert.match(api, /export function getDomesticRouteRules\(routeId\)/)
  assert.match(api, /`\/process-routes\/\$\{routeId\}\/rules`/)
  assert.match(api, /export function saveDomesticRouteRules\(routeId, rules\)/)
  assert.match(api, /export function skipDomesticStep\(data\)/)
  assert.match(api, /post\('\/reports\/skip', data\)/)
  assert.match(api, /export function revokeDomesticSkip\(id\)/)
  assert.match(api, /`\/reports\/skip\/\$\{id\}\/revoke`/)
  assert.match(api, /export function listDomesticSkips\(itemId\)/)
  assert.match(api, /get\('\/reports\/skips', \{ params: \{ item_id: itemId \} \}\)/)
})


test('route management configures generic conditional rules after saving steps', () => {
  const view = read('../src/views/production/ProcessRouteManage.vue')

  assert.match(view, /label="必须扫描" value="required"/)
  assert.match(view, /label="分流判定" value="decision"/)
  assert.match(view, /label="非阻塞可选" value="optional"/)
  assert.match(view, /应用头套网帽模板/)
  assert.match(view, /validateRouteRule/)
  assert.match(view, /getDomesticRouteRules/)
  assert.match(view, /saveDomesticRouteRules/)
  assert.match(view, /跳过/)

  const saveStepsIndex = view.indexOf('await api.saveRouteSteps')
  const saveRulesIndex = view.indexOf('await saveDomesticRouteRules')
  assert.ok(saveStepsIndex >= 0 && saveRulesIndex > saveStepsIndex, '必须先保存路线步骤，再保存条件规则')
})


test('web proxy reporting separates completed work from skipped quantities', () => {
  const view = read('../src/views/domestic/DomesticOrders.vue')

  assert.match(view, /已报/)
  assert.match(view, /应做/)
  assert.match(view, /自动跳过/)
  assert.match(view, /outcome_options/)
  assert.match(view, /异常跳过/)
  assert.match(view, /不计工资/)
  assert.match(view, /DomesticSkipAuditDialog/)
  assert.match(view, /v-permission="'domestic:admin'"[\s\S]*?>异常跳过记录</)
})


test('web proxy submits decision allocations and reloads after manual skip', () => {
  const composable = read('../src/views/domestic/composables/useDomesticOrders.js')

  assert.match(composable, /normalizeOutcomeAllocation/)
  assert.match(composable, /outcomes:/)
  assert.match(composable, /skipDomesticStep/)
  assert.match(composable, /async function confirmSkip/)
  assert.match(composable, /listDomesticSkips/)
  assert.match(composable, /revokeDomesticSkip/)
  assert.match(composable, /async function openSkipAudits/)
  assert.match(composable, /async function handleRevokeSkip/)
  assert.match(composable, /await refreshAll\(\)/)
})


test('manual skip audit dialog exposes only real manual records and keeps revoked rows read-only', () => {
  const dialog = read('../src/views/domestic/components/DomesticSkipAuditDialog.vue')

  assert.match(dialog, /audit\.reason/)
  assert.match(dialog, /audit\.operator_name/)
  assert.match(dialog, /audit\.unit_codes/)
  assert.match(dialog, /audit\.revoked/)
  assert.match(dialog, /v-if="!audit\.revoked"[\s\S]*?v-permission="'domestic:admin'"/)
  assert.match(dialog, /emit\('revoke', audit\)/)
})
