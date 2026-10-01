import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { watchListResourceScope } from '../src/composables/useListResourceScope.js'
import { useTableSort } from '../src/composables/useTableSort.js'
import * as hubResources from '../src/views/customer_hub/customerHubResources.js'
import * as poolState from '../src/views/sales_automation/publicPoolBatchState.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Vue.nextTick() }
const feedback = { msgSuccess() {}, msgSuccessText() {}, msgError() {}, msgWarning() {}, confirmAction: async () => {}, confirmDanger: async () => {} }

function execute(t, path, result, modules = {}, props = {}) {
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const route = Vue.reactive({ query: {}, name: 'AfterSalesList' })
  const defaults = {
    vue: { ...Vue, onMounted() {}, onUnmounted() {}, onBeforeUnmount() {}, onActivated() {} },
    'vue-router': { useRoute: () => route, useRouter: () => ({ replace() {}, push() {} }), onBeforeRouteLeave() {} },
    '@/composables/useListPage': { useListPage: (fetcher, options) => useListPage(fetcher, { ...options, immediate: false }) },
    '@/composables/useAsyncResource': { useAsyncResource },
    '@/composables/useListResourceScope': { watchListResourceScope },
    '@/composables/useTableSort': { useTableSort },
    '@/composables/useTableView': { useTableView: () => ({}) },
    '@/utils/feedback': feedback, '@/utils/datetime': { formatBeijingDateTime: String },
    '@/utils/money': { formatMoney: String }, '@/stores/auth': { useAuthStore: () => ({ hasPermission: () => true }) },
    './expoKioskAuth': { createKioskAuthRecovery: () => () => {} },
    '../customerHubResources': hubResources, './publicPoolBatchState': poolState,
    './composables/useStoreQuota': { useStoreQuota: () => ({ quota: Vue.ref(null), loading: Vue.ref(false), loadQuota() {} }) },
    './operationsPresentation': {}, './presentation': {},
    './workbenchV2Controller': { ITEM_VIEWS: [], createSubmissionIdentity: () => ({ reset() {} }) },
  }
  let source = readFileSync(new URL(path, import.meta.url), 'utf8')
  if (path.endsWith('.vue')) source = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source = source.replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
    const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
    return `const ${declaration} = modules[${JSON.stringify(key)}] || {};`
  }).replace(/export default [^\n]+/g, '').replace(/export /g, '')
  const state = scope.run(() => new Function('modules', 'defineProps', 'defineEmits', 'defineExpose', 'window', `${source}\nreturn ${result};`)(
    { ...defaults, ...modules }, () => Vue.reactive(props), () => () => {}, () => {}, { addEventListener() {}, removeEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) },
  ))
  return { state, route }
}

test('operations adapter exposes first failure, stale rows, retry, and ignores stale metadata', async t => {
  const requests = [], calls = []
  const { state: factory } = execute(t, '../src/views/customer_hub/composables/useOperationsList.js', 'useOperationsList')
  const state = factory((params, config) => { calls.push({ params, config }); const request = deferred(); requests.push(request); return request.promise }, { immediate: false, searchForm: { keyword: '' } })
  let pending = state.fetchList(); requests[0].reject(new Error('unavailable')); assert.equal(await pending, false)
  assert.equal(state.errorMessage.value, 'unavailable'); assert.equal(state.hasLoaded.value, false)
  pending = state.fetchList(); requests[1].resolve({ data: { items: [{ id: 1 }], total: 1, summary: 'current' } }); assert.equal(await pending, true)
  const old = state.handleSearch(); const latest = state.handleSearch()
  requests[3].resolve({ data: { items: [{ id: 2 }], total: 1, summary: 'latest' } }); await latest
  requests[2].resolve({ data: { items: [{ id: 3 }], total: 1, summary: 'old' } }); await old
  assert.equal(state.summary.value, 'latest'); assert.equal(calls[2].config.signal.aborted, true)
  pending = state.fetchList(); requests[4].reject(new Error('refresh failed')); await pending
  assert.deepEqual(state.list.value, [{ id: 2 }]); assert.equal(state.isStale.value, true)
  assert.equal(calls[0].config.suppressToast, true)
})

test('hub list bridge propagates rejection through the real shared controller', async t => {
  let fail = true
  const api = { listCustomers: async () => { if (fail) throw new Error('hub unavailable'); return { data: { items: [{ id: 1 }], total: 1 } } } }
  const { state } = execute(t, '../src/views/customer_hub/composables/useCustomerHub.js', "useCustomerHub('customers', { immediate: false })", { '@/api/customerHub': api })
  assert.equal(await state.fetchList(), false); assert.equal(state.errorMessage.value, 'hub unavailable')
  fail = false; assert.equal(await state.fetchList(), true); assert.equal(state.total.value, 1)
  fail = true; await state.fetchList(); assert.equal(state.isStale.value, true); assert.equal(state.list.value[0].id, 1)
})

for (const resource of [
  { file: 'customer_hub/CustomerDirectory.vue', method: 'listCustomers', meta: 'segmentSummary', payload: { segment_summary: 'latest' } },
  { file: 'customer_hub/WorkbenchList.vue', method: 'listWorkbenchItems', meta: 'summary', payload: { summary: 'latest', count_unit: 'work_item' } },
]) test(`${resource.file} guards metadata and retains rows on read failure`, async t => {
  const queue = [], calls = []
  const { state } = execute(t, `../src/views/${resource.file}`, `{ listPageState, ${resource.meta} }`, {
    '@/api/customerHub': { [resource.method]: (params, config) => { calls.push({ params, config }); const request = deferred(); queue.push(request); return request.promise } },
  }, { customerId: null })
  const first = state.listPageState.fetchList(), second = state.listPageState.fetchList()
  queue[1].resolve({ data: { items: [{ id: 'latest' }], total: 1, ...resource.payload } }); await second
  queue[0].resolve({ data: { items: [{ id: 'old' }], total: 1, ...resource.payload, [resource.meta === 'summary' ? 'summary' : 'segment_summary']: 'old' } }); await first
  assert.equal(state[resource.meta].value, 'latest')
  const failure = state.listPageState.fetchList(); queue[2].reject(new Error('read failed')); await failure
  assert.equal(state.listPageState.errorMessage.value, 'read failed'); assert.equal(state.listPageState.list.value[0].id, 'latest')
  assert.equal(calls[0].config.suppressToast, true)
})

test('workbench rejects action-count payloads instead of presenting them as work items', async t => {
  const { state } = execute(t, '../src/views/customer_hub/WorkbenchList.vue', 'listPageState', {
    '@/api/customerHub': { listWorkbenchItems: async () => ({ data: { count_unit: 'action', items: [{ id: 1 }], total: 1 } }) },
  }, { customerId: null })
  assert.equal(await state.fetchList(), false)
  assert.match(state.errorMessage.value, /事项统计契约/)
  assert.deepEqual(state.list.value, []); assert.equal(state.total.value, 0)
})

test('mail queue uses submitted filters through page changes and failed refreshes', async t => {
  const calls = []; let fail = false
  const { state } = execute(t, '../src/views/mail_outreach/MailOutreachQueue.vue', 'listPageState', { '@/api/mailOutreach': {
    listJobs: async (params, config) => { calls.push({ params, config }); if (fail) throw new Error('mail unavailable'); return { data: { items: [{ id: 1 }], total: 40 } } },
  } })
  state.searchForm.status = 'queued'; await state.handleSearch(); state.searchForm.status = 'draft'
  await state.handlePageChange(2); assert.equal(calls.at(-1).params.status, 'queued')
  fail = true; await state.fetchList(); assert.equal(state.errorMessage.value, 'mail unavailable'); assert.equal(state.list.value.length, 1)
})

test('timeline scope switch clears prior customer rows even when replacement read fails', async t => {
  const requests = [], props = Vue.reactive({ customerId: 1 })
  const { state } = execute(t, '../src/views/customer_hub/workspace/WorkspaceTimeline.vue', 'listPageState', { '@/api/customerHub': {
    listCustomerTimeline: id => { const request = deferred(); requests.push({ ...request, id }); return request.promise },
  } }, props)
  const first = state.fetchList(); requests[0].resolve({ data: { items: [{ id: 'customer-1' }], total: 1 } }); await first
  props.customerId = 2; await Vue.nextTick()
  assert.equal(requests[1].id, 2); assert.deepEqual(state.list.value, []); assert.equal(state.hasLoaded.value, false)
  requests[1].reject(new Error('customer-2 unavailable')); await flush()
  assert.deepEqual(state.list.value, []); assert.equal(state.errorMessage.value, 'customer-2 unavailable')
})

test('salary sorting does not submit pending filters and create/update refresh differ', async t => {
  const calls = []
  const { state } = execute(t, '../src/views/salary/composables/useSalaryProfiles.js', 'useSalaryProfiles()', { '@/api/salary': {
    listProfiles: async params => { calls.push(params); return { data: { items: [{ id: 1 }], total: 41 } } }, createProfile: async () => {}, updateProfile: async () => {},
  } })
  state.searchForm.keyword = 'applied'; await state.handleSearch(); await state.handlePageChange(3)
  state.searchForm.keyword = 'draft'; await state.handleSortChange({ prop: 'name', order: 'descending' })
  assert.equal(calls.at(-1).keyword, 'applied'); assert.equal(calls.at(-1).sort_field, 'name'); assert.equal(calls.at(-1).page, 1)
  await state.handlePageChange(3); state.formRef.value = { validate: async () => true }; state.openEdit({ id: 1 }); await state.submit()
  assert.equal(calls.at(-1).page, 3); state.openCreate(); await state.submit(); assert.equal(calls.at(-1).page, 1)
})

for (const resource of [
  { file: 'color/PaletteView.vue', method: 'getColors', state: 'listPageState', api: '@/api/color', filters: true },
  { file: 'color/BlendView.vue', method: 'getBlends', state: 'listPageState', api: '@/api/color', filters: true },
  { file: 'color/SwatchGenerator.vue', method: 'getSwatches', state: 'historyState', api: '@/api/color' },
  { file: 'insight/IntelligenceOverview.vue', method: 'listIntelligenceReports', state: 'listPageState', api: '@/api/insight' },
]) test(`${resource.file} reads the backend success envelope and keeps failed page data`, async t => {
  const calls = []; let fail = false
  const { state } = execute(t, `../src/views/${resource.file}`, resource.state, { [resource.api]: {
    [resource.method]: async (params, config) => { calls.push({ params, config }); if (fail) throw new Error('unavailable'); return { code: 200, data: { items: [{ id: 1 }], total: 60 } } },
  } })
  if (resource.filters) state.searchForm.keyword = 'applied'
  await state.handleSearch(); assert.deepEqual(state.list.value, [{ id: 1 }])
  if (resource.filters) state.searchForm.keyword = 'draft'
  await state.handlePageChange(2); assert.equal(calls.at(-1).params.page, 2)
  if (resource.filters) assert.equal(calls.at(-1).params.keyword, 'applied')
  fail = true; await state.handlePageChange(3)
  assert.equal(state.dataPage.value, 2); assert.equal(state.isStale.value, true); assert.equal(state.errorMessage.value, 'unavailable')
  assert.equal(calls.at(-1).config.suppressToast, true); assert.ok(calls.at(-1).config.signal instanceof AbortSignal)
})

test('training mine flag belongs to submitted filters through pagination and reset', async t => {
  const calls = []
  const { state } = execute(t, '../src/views/training/TrainingList.vue', 'listPageState', { '@/api/training': {
    listDigests: async params => { calls.push(params); return { code: 200, data: { items: [], total: 0 } } },
  } })
  state.searchForm.mine = true; await state.handleSearch(); state.searchForm.mine = false
  await state.handlePageChange(2); assert.equal(calls.at(-1).mine, true)
  await state.handleReset(); assert.equal(calls.at(-1).mine, undefined); assert.equal(calls.at(-1).page, 1)
})

test('gateway app request scope clears rows and reset keeps the selected app identity', async t => {
  const calls = []; let fail = false
  const { state } = execute(t, '../src/views/system/components/AiGatewayApps.vue', '{ requests, showRequests, resetRequestFilters }', { '@/api/aiGateway': {
    listGatewayRequests: async (id, params) => { calls.push({ id, params }); if (fail) throw new Error('unavailable'); return { data: { items: [{ id }], total: 1 } } },
  } })
  await state.showRequests({ id: 1 }); assert.equal(state.requests.list.value[0].id, 1)
  state.requests.searchForm.status = 'success'; await state.requests.handleSearch()
  fail = true; await state.showRequests({ id: 2 }); assert.deepEqual(state.requests.list.value, [])
  await state.resetRequestFilters(); assert.equal(calls.at(-1).id, 2); assert.equal(calls.at(-1).params.app_id, undefined)
})

test('public pool nested reads keep per-batch rows, reject stale timing and submit local filters explicitly', async t => {
  const queue = [], calls = []
  const { state } = execute(t, '../src/views/sales_automation/PublicPoolResearch.vue', '{ listPageState, loadBatchTasks, batchTasks, batchTasksErrors, visibleBatchTasks, filters, search, resetTaskFilters }', { '@/api/salesAutomation': {
    getPublicPoolBatches: async () => ({ data: { items: [{ id: 1 }], total: 1 } }),
    getPublicPoolTasks: (params, config) => { const request = deferred(); queue.push(request); calls.push({ params, config }); return request.promise },
  } })
  await state.listPageState.fetchList()
  const first = state.loadBatchTasks(1), latest = state.loadBatchTasks(1)
  const row = { id: 1, tier: 'T1', status: 'completed', subject: { display_name: 'Fixture customer' } }
  queue[1].resolve({ data: { items: [row], total: 1 } }); await latest
  queue[0].resolve({ data: { items: [{ ...row, id: 9 }], total: 1 } }); await first
  assert.equal(state.batchTasks.value[1][0].id, 1); assert.equal(calls[0].config.signal.aborted, true)
  state.filters.keyword = 'unmatched'; assert.equal(state.visibleBatchTasks(1).length, 1)
  await state.search(); assert.equal(state.visibleBatchTasks(1).length, 0)
  await state.resetTaskFilters(); assert.equal(state.visibleBatchTasks(1).length, 1)
  const failure = state.loadBatchTasks(1); queue[2].reject(new Error('batch 1 unavailable')); await failure
  assert.equal(state.batchTasks.value[1][0].id, 1); assert.equal(state.batchTasksErrors.value[1], 'batch 1 unavailable')
  const next = state.loadBatchTasks(2); queue[3].reject(new Error('batch 2 unavailable')); await next
  assert.equal(state.batchTasks.value[2], undefined); assert.equal(state.batchTasks.value[1][0].id, 1)
  assert.equal(calls[3].params.batch_id, 2); assert.equal(calls[3].config.suppressToast, true)
})

test('embedded evidence and mail lists clear prior scope; filter reset keeps current customer', async t => {
  const { state: useOperationsList } = execute(t, '../src/views/customer_hub/composables/useOperationsList.js', 'useOperationsList')
  let fail = false
  const props = Vue.reactive({ customerId: 1, kind: 'event', opportunityId: 3, targetStatus: 'contacted', modelValue: [], readonly: true })
  const calls = []
  const { state } = execute(t, '../src/views/customer_hub/EvidencePicker.vue', '{ listPageState, resetFilters }', {
    './composables/useOperationsList': { useOperationsList }, '@/api/customerHub': { listCustomerEvidence: async (id, params, config) => {
      calls.push({ id, params, config }); if (fail) throw new Error('replacement unavailable'); return { data: { items: [{ id }], total: 1 } }
    } },
  }, props)
  await state.listPageState.fetchList(); props.customerId = 2; fail = true; await flush()
  assert.deepEqual(state.listPageState.list.value, []); await state.resetFilters()
  assert.equal(calls.at(-1).id, 2); assert.equal(calls.at(-1).params.opportunity_id, 3); assert.equal(calls.at(-1).params.target_status, 'contacted')
  const mailProps = Vue.reactive({ customerId: 1 })
  const read = async params => { if (fail) throw new Error('mail replacement unavailable'); return { data: { items: [{ id: params.customer_id }], total: 1 } } }
  const { state: mail } = execute(t, '../src/views/customer_hub/mail_outreach/MailOutreachPanel.vue', '{ listPageState, listPageState1 }', {
    '../composables/useOperationsList': { useOperationsList }, '@/api/mailOutreach': { listDrafts: read, listJobs: read },
  }, mailProps)
  fail = false; await Promise.all([mail.listPageState.fetchList(), mail.listPageState1.fetchList()])
  fail = true; mailProps.customerId = 2; await flush()
  assert.deepEqual(mail.listPageState.list.value, []); assert.deepEqual(mail.listPageState1.list.value, [])
  assert.equal(mail.listPageState.errorMessage.value, 'mail replacement unavailable')
})

for (const resource of [
  { file: 'agent-runtime/AgentTaskCenter.vue', api: 'agentRuntime', method: 'getAgentTasks' },
  { file: 'aftersales/AfterSalesList.vue', api: 'aftersales', method: 'getAfterSalesCases' },
  { file: 'announcement/AnnouncementList.vue', api: 'announcement', method: 'get', raw: true },
  { file: 'domestic/DomesticProducts.vue', api: 'domestic', method: 'listProducts' },
  { file: 'domestic/composables/useDomesticCustomers.js', api: 'domestic', method: 'listCustomers', result: 'useDomesticCustomers()' },
  { file: 'domestic/composables/useDomesticCustomerRequests.js', api: 'domestic', method: 'listCustomerRequests', result: 'useDomesticCustomerRequests()' },
  { file: 'expo/StoreManagement.vue', api: 'expo', method: 'getStores', offset: true },
  { file: 'expo/ExpoLeads.vue', api: 'expo', method: 'getLeads' },
  { file: 'expo/PromptVersions.vue', api: 'expo', method: 'getPromptVersions' },
  { file: 'expo/BeautifyPromptVersions.vue', api: 'expo', method: 'getBeautifyPromptVersions' },
  { file: 'sales_automation/SearchJobs.vue', api: 'salesAutomation', method: 'getSearchJobs' },
  { file: 'sales_automation/PublicPoolResearch.vue', api: 'salesAutomation', method: 'getPublicPoolBatches', noFilter: true },
  { file: 'shipping/composables/useInspectionRecords.js', api: 'shipping', method: 'listInspectionRecords', result: 'useInspectionRecords()' },
  { file: 'shipping/composables/useOutboundRecords.js', api: 'shipping', method: 'listOutboundRecords', result: 'useOutboundRecords()' },
  { file: 'card/composables/useCardButler.js', api: 'card', method: 'getCustomers', result: 'useCardButler().customerPage' },
  { file: 'card/composables/useCardButler.js', api: 'card', method: 'getInquiries', result: 'useCardButler().inquiryPage' },
  { file: 'system/components/AiGatewayApps.vue', api: 'aiGateway', method: 'listGatewayApps' },
]) test(`${resource.file}:${resource.method} executes real read failure, stale retry, and snapshot pagination`, async t => {
  const calls = []; let fail = true
  const read = async (...args) => {
    const [params, config] = resource.raw ? args.slice(1) : args
    calls.push({ params, config }); if (fail) throw new Error('fixture unavailable')
    const data = { items: [{ id: 'fixture' }], total: 60 }
    return resource.raw ? data : { code: 200, data }
  }
  const api = resource.raw ? { announcementApi: { get: read } } : { [resource.method]: read }
  const { state } = execute(t, `../src/views/${resource.file}`, resource.result || 'listPageState', { [`@/api/${resource.api}`]: api })
  assert.equal(await state.fetchList(), false); assert.equal(state.errorMessage.value, 'fixture unavailable'); assert.equal(state.hasLoaded.value, false)
  const field = 'keyword' in state.searchForm ? 'keyword' : 'q' in state.searchForm ? 'q' : 'status'
  if (!resource.noFilter) state.searchForm[field] = 'applied'
  fail = false; await state.handleSearch()
  if (!resource.noFilter) state.searchForm[field] = 'draft'
  await state.handlePageChange(2)
  if (!resource.noFilter) assert.equal(calls.at(-1).params[field], 'applied')
  assert.equal(resource.offset ? calls.at(-1).params.offset : calls.at(-1).params.page, resource.offset ? 20 : 2)
  fail = true; await state.fetchList(); assert.equal(state.dataPage.value, 2); assert.equal(state.list.value[0].id, 'fixture'); assert.equal(state.isStale.value, true)
  fail = false; await state.fetchList(); assert.equal(state.errorMessage.value, '')
  assert.equal(calls.at(-1).config.suppressToast, true); assert.ok(calls.at(-1).config.signal instanceof AbortSignal)
})

test('actual directory table empty slot shows the first failure and retry; stale rows remain visible', async t => {
  let state, fail = true
  const listStatus = loadComponent('../../src/components/ListPageStatus.vue', { '@element-plus/icons-vue': {}, './GlassButton.vue': { default: slotShell } })
  const component = loadComponent('../../src/views/customer_hub/CustomerDirectory.vue', {
    vue: { ...Vue, resolveDirective: () => ({}) },
    'vue-router': { useRoute: () => ({ query: {} }), useRouter: () => ({ replace() {} }) },
    '@/api/customerHub': { listCustomers: async () => { if (fail) throw new Error('directory unavailable'); return { data: { items: [{ customer_id: 1, name: 'Retained directory row' }], total: 1 } } } },
    '@/composables/useListPage': { useListPage: (...args) => (state = useListPage(...args)) },
    '@/composables/useListResourceScope': { watchListResourceScope },
    '@/utils/datetime': { formatBeijingDateTime: String }, '@/utils/money': { formatMoney: String }, './operationsPresentation': {},
  })
  const table = { props: ['data'], setup: (props, { slots }) => () => Vue.h('section', {}, props.data.length ? props.data.map(row => Vue.h('p', row.name)) : slots.empty?.()) }
  const registrations = { ListPageStatus: listStatus, FilterBar: slotShell, GlassButton: slotShell, ElTable: table, ElTableColumn: slotShell, StatusBadge: slotShell, ElAlert: slotShell, ElInput: slotShell, ElSelect: slotShell, ElOption: slotShell, ElEmpty: slotShell, ElPagination: slotShell }
  const mounted = mountComponent(t, component, {}, undefined, registrations)
  await flush(); assert.match(mounted.text(), /directory unavailable/)
  const retry = mounted.find(node => node.props?.onClick && /重试加载/.test([node.text, ...(node.children || []).map(child => child.text)].join('')))[0]
  assert.ok(retry); fail = false; retry.props.onClick(); await flush(); assert.match(mounted.text(), /Retained directory row/)
  fail = true; await state.fetchList(); await flush(); assert.match(mounted.text(), /Retained directory row/); assert.match(mounted.text(), /directory unavailable/)
})

test('real timeline template renders first-failure retry and keeps rows for stale refresh', async t => {
  let fail = true
  const listStatus = loadComponent('../../src/components/ListPageStatus.vue', { '@element-plus/icons-vue': {}, './GlassButton.vue': { default: slotShell } })
  const component = loadComponent('../../src/views/customer_hub/workspace/WorkspaceTimeline.vue', {
    vue: { ...Vue, resolveDirective: () => ({}) },
    '@/api/customerHub': { listCustomerTimeline: async () => { if (fail) throw new Error('timeline unavailable'); return { data: { items: [{ event_id: 1, title: 'Visible customer event' }], total: 1 } } } },
    '@/composables/useListPage': { useListPage }, '@/utils/datetime': { formatBeijingDateTime: String },
  })
  const registrations = { ListPageStatus: listStatus, GlassButton: slotShell, ElAlert: slotShell, ElTimeline: slotShell, ElTimelineItem: slotShell, ElEmpty: slotShell, ElPagination: slotShell }
  const mounted = mountComponent(t, component, { customerId: 1 }, undefined, registrations)
  await flush(); assert.match(mounted.text(), /timeline unavailable/)
  const retry = mounted.find(node => node.props?.onClick && /重试加载/.test([node.text, ...(node.children || []).map(child => child.text)].join('')))[0]
  assert.ok(retry); fail = false; await retry.props.onClick(); await flush(); assert.match(mounted.text(), /Visible customer event/)
  fail = true; await retry.props.onClick(); await flush(); assert.match(mounted.text(), /Visible customer event/); assert.match(mounted.text(), /timeline unavailable/)
})

test('actual API wrappers preserve signal, suppressToast, scope and query parameters', async t => {
  const calls = [], config = { signal: new AbortController().signal, suppressToast: true }, params = { page: 2, page_size: 20, keyword: 'fixture' }
  const client = { interceptors: { response: { use() {} } }, get: async (path, options) => { calls.push({ path, options }); return { code: 200, data: { items: [], total: 0 } } } }
  const clients = new Proxy({}, { get: () => client })
  const definitions = [
    ['aftersales', 'getAfterSalesCases'], ['agentRuntime', 'getAgentTasks'], ['aiGateway', 'listGatewayApps'],
    ['card', 'getCustomers'], ['card', 'getInquiries'], ['domestic', 'listCustomers'], ['domestic', 'listCustomerRequests'], ['domestic', 'listProducts'],
    ['expo', 'getStores'], ['expo', 'getLeads'], ['expo', 'getPromptVersions'], ['expo', 'getBeautifyPromptVersions'],
    ['mailOutreach', 'listDrafts'], ['mailOutreach', 'listJobs'], ['salary', 'listProfiles'],
    ['salesAutomation', 'getSearchJobs'], ['salesAutomation', 'getPublicPoolBatches'], ['salesAutomation', 'getPublicPoolTasks'],
    ['shipping', 'listInspectionRecords'], ['shipping', 'listOutboundRecords'], ['training', 'listDigests'],
    ['color', 'getColors'], ['color', 'getBlends'], ['color', 'getSwatches'], ['insight', 'listIntelligenceReports'],
    ['customerHubContract', 'listQualificationQueue'], ['customerHubContract', 'listCustomers'], ['customerHubContract', 'listWorkbenchItems'],
    ['customerHubContract', 'listSearchJobs'], ['customerHubContract', 'listResearchTasks'], ['customerHubContract', 'listOpportunities'], ['customerHubContract', 'listActions'],
  ]
  for (const [file, method] of definitions) {
    const { state } = execute(t, `../src/api/${file}.js`, file === 'customerHubContract' ? `createCustomerHubApi(modules.client).${method}` : method, { './clients': clients, client })
    await state(params, config)
    assert.deepEqual(calls.at(-1).options.params, params, `${file}.${method} params`)
    assert.equal(calls.at(-1).options.signal, config.signal, `${file}.${method} signal`)
    assert.equal(calls.at(-1).options.suppressToast, true, `${file}.${method} suppressToast`)
  }
  for (const [file, expression] of [['aiGateway', 'listGatewayRequests'], ['customerHubContract', 'listCustomerTimeline'], ['customerHubContract', 'listCustomerEvidence'], ['battleReport', 'battleReportApi.orders']]) {
    const { state } = execute(t, `../src/api/${file}.js`, file === 'customerHubContract' ? `createCustomerHubApi(modules.client).${expression}` : expression, { './clients': clients, client })
    await state(42, params, config)
    assert.deepEqual(calls.at(-1).options.params, params); assert.equal(calls.at(-1).options.signal, config.signal); assert.equal(calls.at(-1).options.suppressToast, true)
  }
  const { state } = execute(t, '../src/api/announcement.js', 'announcementApi.get', { './clients': clients })
  await state('/list', params, config)
  assert.deepEqual(calls.at(-1).options.params, params); assert.equal(calls.at(-1).options.signal, config.signal)
})
