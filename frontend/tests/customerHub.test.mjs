import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('customer hub API uses only the registered customer hub client', () => {
  const clients = read('../src/api/clients.js')
  const api = read('../src/api/customerHub.js')
  const contract = read('../src/api/customerHubContract.js')

  assert.match(clients, /customerHubClient\s*=\s*createApiClient\(\{\s*baseURL:\s*['"]\/api\/customer-hub['"]/)
  assert.match(api, /import\s*\{\s*customerHubClient\s*\}\s*from\s*['"]\.\/clients['"]/)
  assert.doesNotMatch(api + contract, /axios|createApiClient|\/api\/insight|\/api\/sales/)
})

test('customer hub list state exposes loading empty error and stale guidance', () => {
  const composable = read('../src/views/customer_hub/composables/useCustomerHub.js')
  const workspace = read('../src/views/customer_hub/CustomerHubWorkspace.vue')

  assert.match(composable, /useListPage/)
  assert.match(composable, /loading\s*=\s*ref\(false\)/)
  assert.match(composable, /empty\s*=\s*computed/)
  assert.match(composable, /errorGuidance\s*=\s*computed/)
  assert.match(composable, /staleGuidance\s*=\s*computed/)
  assert.match(composable, /重新加载/)
  assert.match(composable, /数据可能已过期/)
  assert.match(composable, /page_size/)
  assert.match(composable, /async function requeueJob/)
  assert.match(composable, /requestId !== listRequest/)
  assert.match(composable, /currentCustomerId\.value !== id/)
  assert.match(composable, /currentCustomerId\.value === customerId/)
  assert.match(composable, /detailError/)
  assert.match(composable, /timelineError/)
  assert.match(composable, /if \(requestId === listRequest\) loading\.value = false/)
  assert.match(composable, /currentCustomerId\.value === customerId\) timelineError\.value = caught/)
  assert.doesNotMatch(workspace, /from ['"]@\/api\/customerHub['"]/)
  assert.match(workspace, /:row-key="rowKey"/)
  assert.match(workspace, /row\.job_id \|\| row\.research_task_id \|\| row\.opportunity_id \|\| row\.action_id \|\| row\.customer_id/)
  assert.match(workspace, /v-any-permission="\['sales_automation:write', 'sales_automation:admin'\]"/)
  assert.match(workspace, /v-any-permission="\['customer_radar:write', 'customer:admin'\]"/)
})

test('new acquisition and research entries retain create configure and review workflows', () => {
  const acquisition = read('../src/views/customer_hub/AcquisitionTasks.vue')
  const research = read('../src/views/customer_hub/ResearchCenter.vue')
  assert.match(acquisition, /配置获客模型/)
  assert.match(acquisition, /创建获客任务/)
  assert.match(acquisition, /saveProfile/)
  assert.match(acquisition, /createJob/)
  assert.match(acquisition, /v-permission="'sales_automation:admin'"/)
  assert.match(acquisition, /v-any-permission="\['sales_automation:write','sales_automation:admin'\]"/)
  assert.match(acquisition, /策略 JSON 格式错误/)
  assert.match(research, /创建公海批次/)
  assert.match(research, /通过复核/)
  assert.match(research, /要求修订/)
  assert.match(research, /reviewTask/)
  assert.match(research, /配额 JSON 格式错误/)
})

test('navigation consolidates five customer operations entries under existing permissions', () => {
  const navigation = read('../src/config/navigation.js')

  for (const [path, permission] of [
    ['/customer-hub/customers', 'customer:read'],
    ['/customer-hub/acquisition', 'sales_automation:read'],
    ['/customer-hub/research', 'sales_automation:read'],
    ['/customer-hub/opportunities', 'customer_opportunity:read'],
    ['/customer-hub/radar', 'customer_radar:read'],
  ]) {
    const start = navigation.indexOf(`path: '${path}'`)
    assert.notEqual(start, -1, `missing ${path}`)
    assert.match(navigation.slice(start, start + 520), new RegExp(`(?:permission|anyPermission):[^}]*${permission.replace(':', '\\:')}`))
  }
  assert.doesNotMatch(navigation, /\/sales-automation\/leads|CustomerOpportunityView|CustomerRadarView/)
  const acquisition = navigation.slice(navigation.indexOf("path: '/customer-hub/acquisition'"), navigation.indexOf("path: '/customer-hub/research'"))
  const research = navigation.slice(navigation.indexOf("path: '/customer-hub/research'"), navigation.indexOf("path: '/customer-hub/opportunities'"))
  assert.doesNotMatch(acquisition, /customer:read_all/)
  assert.doesNotMatch(research, /sales_automation:(?:write|admin)/)
})

test('customer detail drawer progressively loads timeline and names all profile sections', () => {
  const drawer = read('../src/views/customer_hub/CustomerDetailDrawer.vue')

  assert.match(drawer, /overview/)
  for (const section of ['identity', 'contacts', 'conversations', 'orders', 'evidence', 'opportunities', 'actions', 'annotations', 'version quality']) {
    assert.match(drawer.toLowerCase(), new RegExp(section.replace(' ', '.{0,3}')))
  }
  assert.match(drawer, /@tab-change="handleTabChange"/)
  assert.match(drawer, /loadTimeline/)
  assert.match(drawer, /watch\(\(\) => props\.customer\?\.customer_id/)
  assert.match(drawer, /activeTab\.value = 'overview'/)
  assert.match(drawer, /客户详情加载失败/)
  assert.match(drawer, /时间线加载失败/)
})
