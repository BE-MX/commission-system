import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const navigation = read('../src/config/navigation.js')
const clients = read('../src/api/clients.js')
const api = read('../src/api/salesAutomation.js')
const jobs = read('../src/views/sales_automation/SearchJobs.vue')
const leads = read('../src/views/sales_automation/LeadPool.vue')
const publicPool = read('../src/views/sales_automation/PublicPoolResearch.vue')
const matrix = read('../src/views/system/composables/usePermissionMatrix.js')

test('intelligent acquisition has one navigation group and three goal pages', () => {
  assert.match(navigation, /salesAutomation:\s*\{/)
  for (const path of ['/sales-automation/profile', '/sales-automation/jobs', '/sales-automation/leads']) {
    assert.ok(navigation.includes(`path: '${path}'`), `${path} should be registered`)
  }
  assert.match(matrix, /sales_automation:\s*'智能获客'/)
})

test('all sales automation calls share the short-lived domain client', () => {
  assert.match(clients, /salesAutomationClient.*baseURL: '\/api\/sales-automation'.*timeout: 30000/)
  assert.match(api, /salesAutomationClient/)
  assert.doesNotMatch(api, /axios\.create|createApiClient/)
})

test('search is asynchronous and list pages use the standard orchestrator', () => {
  assert.match(jobs, /useListPage/)
  assert.match(jobs, /setTimeout\(async \(\) =>/)
  assert.match(jobs, /createSearchJob/)
  assert.match(jobs, /requeueSearchJob/)
  assert.doesNotMatch(jobs, /创建并启动/)
  assert.match(leads, /useListPage/)
  assert.match(leads, /DetailDrawer/)
})

test('research evidence is rendered as text with source, capture time and confidence', () => {
  assert.doesNotMatch(leads, /v-html/)
  assert.match(leads, /fact\.claim/)
  assert.match(leads, /fact\.source_url/)
  assert.match(leads, /fact\.captured_at/)
  assert.match(leads, /fact\.confidence/)
})

test('public-pool dedupe and score-70 deep research are visible to sales users', () => {
  assert.match(jobs, /public_pool_deduplicated_count/)
  assert.match(leads, /公海重复/)
  assert.match(leads, /public_pool_research/)
  assert.match(leads, /结构化成交研判/)
  assert.match(publicPool, /智能获客 70 分以上候选/)
  assert.match(publicPool, /source_system === 'ark_lead'/)
})
