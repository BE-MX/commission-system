import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const navigation = read('../src/config/navigation.js')
const clients = read('../src/api/clients.js')
const api = read('../src/api/salesAutomation.js')
const jobs = read('../src/views/sales_automation/SearchJobs.vue')
const publicPool = read('../src/views/sales_automation/PublicPoolResearch.vue')
const matrix = read('../src/views/system/composables/usePermissionMatrix.js')
const publicPoolBatchState = await import('../src/views/sales_automation/publicPoolBatchState.js')

test('intelligent acquisition is consolidated into customer operations navigation', () => {
  assert.match(navigation, /customerOperations:\s*\{/)
  assert.ok(navigation.includes("path: '/customer-hub/acquisition'"))
  assert.ok(navigation.includes("path: '/customer-hub/research'"))
  assert.doesNotMatch(navigation, /\/sales-automation\/leads/)
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
})

test('public-pool dedupe and score-70 deep research are visible to sales users', () => {
  assert.match(jobs, /public_pool_deduplicated_count/)
  assert.match(publicPool, /智能获客 70 分以上候选/)
  assert.match(publicPool, /source_system === 'ark_lead'/)
})

test('public-pool renders batch tree, status tabs and atomic bulk review actions', () => {
  assert.match(publicPool, /class="batch-tree"/)
  assert.match(publicPool, /toggleBatch\(batch\)/)
  assert.match(publicPool, /statusTabs/)
  assert.match(publicPool, /整批通过/)
  assert.match(publicPool, /整批拒绝/)
  assert.match(publicPool, /筛选只影响明细显示，整批操作始终覆盖完整批次/)
  assert.match(publicPool, /getPublicPoolTasks\(\{ batch_id: batchId, page: 1, page_size: 300 \}\)/)
  assert.match(publicPool, /Promise\.all\(expandedBatchIds\.value\.map\(loadBatchTasks\)\)/)
  assert.match(publicPool, /scope === 'selected'\) payload\.task_ids = taskIds/)
  assert.match(api, /bulkReviewPublicPoolTasks/)
  assert.match(api, /\/public-pool\/tasks\/bulk-review/)
})

test('public-pool task statuses map to one batch tab each', () => {
  const { defaultBatchTab, taskStatusBucket, taskStatusCounts } = publicPoolBatchState
  const tasks = [
    { status: 'pending', review_status: 'pending' },
    { status: 'running', review_status: 'pending' },
    { status: 'completed', review_status: 'pending' },
    { status: 'completed', review_status: 'approved' },
    { status: 'completed', review_status: 'rejected' },
    { status: 'failed', review_status: 'pending' },
  ]
  assert.deepEqual(tasks.map(taskStatusBucket), [
    'pending', 'running', 'pending_review', 'approved', 'rejected', 'failed',
  ])
  assert.deepEqual(taskStatusCounts(tasks), {
    pending_review: 1, pending: 1, running: 1, approved: 1, rejected: 1, failed: 1,
  })
  assert.equal(defaultBatchTab(tasks), 'pending_review')
})
