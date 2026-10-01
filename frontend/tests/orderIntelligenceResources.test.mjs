import test from 'node:test'
import assert from 'node:assert/strict'
import { clearListResource } from '../src/composables/useListResourceScope.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useListPage } from '../src/composables/useListPage.js'
import { viewController } from './helpers/viewController.mjs'
import * as Vue from 'vue'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function setup(t, overrides = {}) {
  const calls = []
  const api = {
    getOrderIntelligenceFilters: async () => ({ can_read_all: true, users: [], teams: [], countries: [], country_tree: [], models: [], colors: [], source_categories: [] }),
    getOrderOverview: async params => ({ period: params.date_to }),
    getCountryAnalysis: async () => ({ items: [{ id: 'country' }], total: 1 }),
    getPeopleAnalysis: async () => ({ items: [], total: 0 }),
    getCustomerProfileAnalysis: async () => ({ items: [], total: 0 }),
    getCustomerActions: async (params, config) => { calls.push(params); assert.equal(config.suppressToast, true); assert.ok(config.signal); return { items: [{ id: 1 }], total: 101, risk_definition: 'current' } },
    ...overrides,
  }
  const { vm } = viewController(t, '../../src/views/order_intelligence/composables/useOrderIntelligence.js', 'useOrderIntelligence', {
    '@/api/orderIntelligence': api, '@/composables/useListResourceScope': { clearListResource },
  })
  return { state: vm.useOrderIntelligence(), calls }
}

test('explicit clearing cancels a pending list or auxiliary read before it can repopulate old scope', async () => {
  const pending = deferred(), list = useListPage(() => pending.promise, { immediate: false })
  const reading = list.fetchList(); clearListResource(list)
  pending.resolve({ items: [{ id: 'old-scope' }], total: 1 }); assert.equal(await reading, false)
  assert.deepEqual(list.list.value, []); assert.equal(list.loading.value, false); assert.equal(list.hasLoaded.value, false)
  const late = deferred(), resource = useAsyncResource(() => late.promise, { initialData: [] })
  const old = resource.load(1); resource.clear(); late.resolve(['old-scope'])
  assert.equal(await old, false); assert.deepEqual(resource.data.value, []); assert.equal(resource.hasLoaded.value, false)
})

test('customer pagination and AI use submitted analysis plus submitted local filters', async t => {
  let briefParams
  const { state, calls } = setup(t, { generateOrderAiBrief: async params => { briefParams = params; return { status: 'succeeded', content: 'ready' } } })
  state.activeTab.value = 'customers'
  state.filters.dateRange = ['2026-01-01', '2026-06-30']; state.filters.models = ['A']; state.filters.countryPaths = [['Europe', 'DE']]
  await state.applyAnalysis()
  state.customerFilters.country = 'DE'; await state.customerState.handleSearch()
  state.filters.dateRange[1] = '2026-09-30'; state.filters.models.push('B'); state.customerFilters.country = 'FR'
  await state.changeCustomerPage(3)
  assert.equal(calls.at(-1).page, 3); assert.equal(calls.at(-1).country, 'DE'); assert.equal(calls.at(-1).as_of, '2026-06-30')
  assert.deepEqual(calls.at(-1).models, ['A']); assert.deepEqual(calls.at(-1).countries, ['DE'])
  await state.generateBrief()
  assert.equal(briefParams.date_to, '2026-06-30'); assert.deepEqual(briefParams.models, ['A'])
  await state.changeCustomerSize(50); assert.equal(calls.at(-1).page, 1); assert.equal(calls.at(-1).page_size, 50)
})

test('each aggregate commits only the latest response and retains successful data on a failed retry', async t => {
  for (const [tab, method, key] of [['countries', 'getCountryAnalysis', 'countriesResource'], ['people', 'getPeopleAnalysis', 'peopleResource'], ['profiles', 'getCustomerProfileAnalysis', 'profilesResource']]) {
    const queue = [], { state } = setup(t, { [method]: (params, config) => { const request = deferred(); queue.push({ ...request, params, config }); return request.promise } })
    state.activeTab.value = tab
    const old = state.changeTab(), latest = state.changeTab()
    queue[1].resolve({ items: [{ id: 'new' }], total: 1 }); await latest
    queue[0].resolve({ items: [{ id: 'old' }], total: 1 }); await old
    assert.equal(state[key].data.value.items[0].id, 'new'); assert.equal(queue[0].config.signal.aborted, true)
    const failure = state.changeTab(); queue[2].reject(Error('analysis offline')); await failure
    assert.equal(state[key].errorMessage.value, 'analysis offline'); assert.equal(state[key].data.value.items[0].id, 'new')
  }
})

test('global query invalidates hidden customer and aggregate reads without applying local drafts', async t => {
  const pendingCustomer = deferred(), pendingCountries = deferred(); let call = 0
  const { state } = setup(t, {
    getCustomerActions: async () => { if (++call === 1) return pendingCustomer.promise; return { items: [], total: 0 } },
    getCountryAnalysis: () => pendingCountries.promise,
  })
  state.activeTab.value = 'customers'; const oldCustomer = state.changeTab()
  state.activeTab.value = 'countries'; const oldCountry = state.changeTab()
  state.activeTab.value = 'overview'; state.filters.models = ['changed']; await state.applyAnalysis()
  pendingCustomer.resolve({ items: [{ id: 'old-customer' }], total: 1, risk_definition: 'old' })
  pendingCountries.resolve({ items: [{ id: 'old-country' }], total: 1 })
  await Promise.all([oldCustomer, oldCountry])
  assert.deepEqual(state.customers.items, []); assert.equal(state.customers.risk_definition, undefined)
  assert.equal(state.countriesResource.data.value, null)
})

test('overview/options failures are independent and latest metadata cannot overwrite current choices', async t => {
  const queue = [], { state } = setup(t, { getOrderIntelligenceFilters: () => { const request = deferred(); queue.push(request); return request.promise }, getOrderOverview: async () => { throw Error('overview offline') } })
  const old = state.loadPage(), latest = state.loadPage()
  queue[1].resolve({ can_read_all: true, users: [{ user_id: 2 }], countries: [] }); await latest
  queue[0].resolve({ can_read_all: false, users: [{ user_id: 1 }], countries: [] }); await old
  assert.equal(state.options.value.users[0].user_id, 2); assert.equal(state.overviewResource.errorMessage.value, 'overview offline')
  state.activeTab.value = 'customers'; await state.changeTab(); assert.equal(state.customers.items.length, 1)
})

test('slow restored AI brief cannot replace a brief the user has just generated', async t => {
  const restored = deferred(), mounted = []
  const { vm } = viewController(t, '../../src/views/order_intelligence/composables/useOrderIntelligence.js', 'useOrderIntelligence', {
    vue: { ...Vue, onMounted: fn => mounted.push(fn), onBeforeUnmount() {} },
    '@/composables/useListResourceScope': { clearListResource },
    '@/api/orderIntelligence': {
      getActiveOrderAiBrief: () => restored.promise,
      getOrderOverview: async () => ({}), getOrderIntelligenceFilters: async () => ({}),
      generateOrderAiBrief: async () => ({ job_id: 'new-job', status: 'succeeded', content: 'new content' }),
    },
  })
  const state = vm.useOrderIntelligence(); mounted[0]()
  await state.generateBrief(); restored.resolve({ job_id: 'old-job', status: 'succeeded', content: 'old content' })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(state.aiBrief.value.job_id, 'new-job'); assert.equal(state.aiBrief.value.content, 'new content')
})
