import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { clearListResource } from '../src/composables/useListResourceScope.js'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function controller(t, path, name, overrides = {}) {
  const scope = Vue.effectScope(), events = []
  const route = Vue.reactive({ path: '/shipping/outbound', query: {} })
  const modules = {
    vue: Vue, 'vue-router': { useRoute: () => route },
    '@/composables/useListPage': { useListPage: (fn, options) => useListPage(fn, { ...options, immediate: false }) },
    '@/composables/useListResourceScope': { clearListResource },
    '@/utils/feedback': {}, '@/utils/download': {}, '../print/printDocs': {},
    ...overrides,
  }
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => `const ${binding.replace(/\bas\b/g, ':')} = modules[${JSON.stringify(key)}];`)
    .replace(/export /g, '')
  const window = { dispatchEvent: event => events.push(event.type) }
  const api = scope.run(() => new Function('modules', 'window', `${source}\nreturn ${name}();`)(modules, window))
  t.after(() => { api.state?.cancel(); scope.stop() })
  return { api, route, events }
}
const problemPath = '../src/views/shipping/composables/useOutboundProblems.js'

test('refreshing a shrinking last page returns to remaining current problems', async t => {
  const calls = []
  const { api } = controller(t, problemPath, 'useOutboundProblems', {
    '@/api/invoice': { getOutboundProblems: async params => {
      calls.push(params.page)
      return { items:params.page === 1 ? [{key:'still-abnormal'}] : [],total:20,checked_at:'now' }
    } },
  })
  api.state.page.value = 2
  await api.load()
  assert.deepEqual(calls, [2, 1])
  assert.equal(api.state.page.value, 1)
  assert.equal(api.state.isEmpty.value, false)
  assert.equal(api.state.list.value[0].key, 'still-abnormal')
})

test('closing or changing identity clears problem rows and ignores a late response', async t => {
  const first = deferred(), second = deferred(), requests = []
  const { api, events } = controller(t, problemPath, 'useOutboundProblems', {
    '@/api/invoice': { getOutboundProblems: (params, config) => { requests.push(config); return requests.length === 1 ? first.promise : second.promise } },
  })
  const old = api.load()
  api.reset()
  assert.equal(requests[0].signal.aborted, true)
  const current = api.load()
  second.resolve({ items: [{ key:'task:350', number:'Daisy-KC-0907' }], total:1, checked_at:'2026-10-08 23:30:00' })
  await current
  first.resolve({ items: [{ key:'private', number:'Old account' }], total:1, checked_at:'old' })
  await old
  assert.equal(api.state.list.value[0].number, 'Daisy-KC-0907')
  assert.equal(api.checkedAt.value, '2026-10-08 23:30:00')
  assert.deepEqual(events, ['ark-document-anomalies-changed'])
  api.reset()
  assert.deepEqual(api.state.list.value, [])
  assert.equal(api.checkedAt.value, null)
})

test('failed problem refresh retains evidence as stale, never reports no problems', async t => {
  let failed = false
  const { api } = controller(t, problemPath, 'useOutboundProblems', {
    '@/api/invoice': { getOutboundProblems: async () => {
      if (failed) throw Error('temporarily unavailable')
      return { items:[{key:'event:3341',number:'Existing problem'}],total:1,checked_at:'checked' }
    } },
  })
  await api.load(); failed = true; await api.load()
  assert.equal(api.state.list.value.length, 1)
  assert.equal(api.state.isStale.value, true)
  assert.equal(api.state.isEmpty.value, false)
  assert.equal(api.state.errorMessage.value, 'temporarily unavailable')
  assert.equal(api.location({ target:null }), null)
  assert.deepEqual(api.location({key:'task:350',target:{order_id:'105819851896460'}}),
    {path:'/shipping/outbound',query:{order_id:'105819851896460',problem:'task:350',problem_focus:'1'}})
})

test('problem navigation on the mounted outbound page clears conflicting filters and starts at page one', async t => {
  const calls = []
  const { api, route } = controller(t, '../src/views/shipping/composables/useOutboundRecords.js', 'useOutboundRecords', {
    '@/api/shipping': { listOutboundRecords: async params => { calls.push({...params}); return {data:{items:[],total:0}} } },
  })
  Object.assign(api.searchForm, { outboundState:'ready',inspectionStatus:'submitted',keyword:'old',dateRange:['2026-10-01','2026-10-02'] })
  api.page.value = 4
  route.query = { order_id:'105819851896460', problem:'task:350' }
  await Vue.nextTick()
  assert.deepEqual(calls.at(-1), {page:1,page_size:20,order_id:'105819851896460'})
  route.query = {keyword:'宋皓月浅色库存#0906 $459',problem:'event:3341'}
  await Vue.nextTick()
  assert.deepEqual(calls.at(-1), {page:1,page_size:20,keyword:'宋皓月浅色库存#0906 $459'})
  Object.assign(api.searchForm, {outboundState:'ready',keyword:'changed'})
  route.query = {...route.query, problem_focus:'2'}
  await Vue.nextTick()
  assert.deepEqual(calls.at(-1), {page:1,page_size:20,keyword:'宋皓月浅色库存#0906 $459'})
  const count = calls.length
  route.path = '/invoice/manage'; route.query = {}
  await Vue.nextTick()
  assert.equal(calls.length, count)
})
