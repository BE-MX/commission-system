import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as announcementPresentation from '../src/views/announcement/presentation.js'
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

test('card salespersons expose first/stale failures; a successful write cannot fail because the list read fails', async t => {
  let fail = true
  const { vm, messages } = viewController(t, '../../src/views/card/composables/useCardButler.js', 'useCardButler', { '@/api/card': {
    getSalespersons: async config => { assert.equal(config.suppressToast, true); if (fail) throw Error('salespersons offline'); return { data: [{ id: 1 }] } },
    upsertSalesperson: async () => { fail = true },
  } })
  const state = vm.useCardButler(); assert.equal(await state.fetchSalespersons(), false)
  assert.equal(state.salespersonsResource.hasLoaded.value, false); fail = false; await state.fetchSalespersons()
  Object.assign(state.spForm, { slug: 'person', name: 'Fixture', email: 'fixture@example.com' }); await state.saveSalesperson()
  assert.equal(state.salespersons.value[0].id, 1); assert.equal(state.salespersonsResource.isStale.value, true); assert.ok(messages.includes('保存'))
})

test('card entries switch and close clear former customer rows and reject late requests', async t => {
  const oldRead = deferred(); let fail = false
  const { vm } = viewController(t, '../../src/views/card/composables/useCardButler.js', 'useCardButler', { '@/api/card': {
    getEntries: async (id, config) => { assert.equal(config.suppressToast, true); if (id === 1) return oldRead.promise; if (fail) throw Error('entries offline'); return { data: [{ id }] } },
  } })
  const state = vm.useCardButler(), old = state.openEntries({ id: 1 }); await state.openEntries({ id: 2 })
  oldRead.resolve({ data: [{ id: 1 }] }); await old; assert.equal(state.entries.value[0].id, 2)
  fail = true; await state.refreshEntries(); assert.equal(state.entriesResource.isStale.value, true); assert.equal(state.entries.value[0].id, 2)
  state.entriesVisible.value = false; await nextTick(); assert.deepEqual(state.entries.value, []); assert.equal(state.currentCustomer.value, null)
})

test('card multi-attachment entry writes retain the original customer and content snapshot', async t => {
  const first = deferred(), writes = []
  const { vm } = viewController(t, '../../src/views/card/composables/useCardButler.js', 'useCardButler', { '@/api/card': {
    getEntries: async id => ({ data: [{ id }] }), getCustomers: async () => ({ data: { items: [], total: 0 } }),
    createEntry: async (id, payload) => { writes.push({ id, payload }); if (writes.length === 1) await first.promise },
  } })
  const state = vm.useCardButler(); await state.openEntries({ id: 1 })
  state.entryForm.title = 'original title'; state.entryForm.content = 'original content'
  state.entryFiles.value = [{ path: 'file-1' }, { path: 'file-2' }]
  const saving = state.saveEntry(); await state.openEntries({ id: 2 }); state.entryForm.title = 'new draft'
  first.resolve(); await saving
  assert.deepEqual(writes.map(write => write.id), [1, 1]); assert.deepEqual(writes.map(write => write.payload.title), ['original title', 'original title'])
  assert.equal(writes[0].payload.content, 'original content'); assert.equal(writes[1].payload.content, null)
  assert.equal(state.entryForm.title, 'new draft'); assert.equal(state.currentCustomer.value.id, 2)
})

test('announcement weekly first/stale failure and generate/read-failure preserve queued success', async t => {
  let fail = true
  const { vm, messages } = viewController(t, '../../src/views/announcement/AnnouncementWeekly.vue', 'weeklyResource,rows,load,generate', {
    './presentation.js': announcementPresentation, '@/api/announcement': { announcementApi: {
      get: async (path, params, config) => { assert.equal(config.suppressToast, true); if (fail) throw Error('weekly offline'); return [{ id: 1 }] },
      post: async () => { fail = true },
    } },
  })
  assert.equal(await vm.load(), false); assert.equal(vm.weeklyResource.hasLoaded.value, false)
  fail = false; await vm.load(); await vm.generate(false)
  assert.equal(vm.rows.value[0].id, 1); assert.equal(vm.weeklyResource.isStale.value, true); assert.ok(messages.includes('加入周报生成队列'))
})

test('announcement initialization failure is distinct from an uninitialized library and config/member reads settle separately', async t => {
  let configFails = true, membersFail = false
  const { vm, messages } = viewController(t, '../../src/views/announcement/AnnouncementSettings.vue', 'configResource,categoryResource,membersResource,load,initialize,saveMembers', {
    './presentation.js': announcementPresentation, '@/api/announcement': { announcementApi: {
      get: async (path, params, config) => {
        assert.equal(config.suppressToast, true)
        if (path === '/config') { if (configFails) throw Error('config offline'); return { initialized: true } }
        if (path === '/members' && membersFail) throw Error('members offline')
        return [{ id: 1, user_id: 1, role: 'viewer' }]
      },
      post: async () => {}, put: async () => { configFails = true },
    } },
  })
  assert.equal(await vm.load(), false); assert.equal(vm.configResource.hasLoaded.value, false)
  await vm.initialize(); assert.ok(messages.some(message => message.event === 'updated'))
  configFails = false; membersFail = true; await vm.load()
  assert.equal(vm.categoryResource.data.value[0].id, 1); assert.equal(vm.membersResource.errorMessage.value, 'members offline')
  membersFail = false; await vm.load(); await vm.saveMembers(); assert.ok(messages.includes('保存成员'))
  assert.equal(vm.configResource.errorMessage.value, 'config offline')
})

test('announcement delivery refresh failure preserves rows and candidate search rejects old queries', async t => {
  const old = deferred(); let fail = false
  const { vm } = viewController(t, '../../src/views/announcement/AnnouncementSettings.vue', 'deliveriesResource,loadDeliveries,peopleResource,searchPeople', {
    './presentation.js': announcementPresentation, '@/api/announcement': { announcementApi: {
      get: async (path, params) => {
        if (path === '/member-candidates') return params.q === 'old' ? old.promise : [{ user_id: 'new' }]
        if (fail) throw Error('deliveries offline'); return [{ id: 1 }]
      },
    } },
  })
  await vm.loadDeliveries(); fail = true; await vm.loadDeliveries(); assert.equal(vm.deliveriesResource.isStale.value, true)
  const pending = vm.searchPeople('old'); await vm.searchPeople('new'); old.resolve([{ user_id: 'old' }]); await pending
  assert.equal(vm.peopleResource.data.value[0].user_id, 'new')
})

test('operations polling and mutation refresh use committed status and retain independent successful overview', async t => {
  let failRuns = false; const calls = []
  const { vm } = viewController(t, '../../src/views/system/composables/useOperationsCenter.js', 'useOperationsCenter', {
    '@/api/clients': { operationsClient: { get: async (path, config) => {
      assert.equal(config.suppressToast, true)
      if (path === '/overview') return { data: { summary: { healthy_services: 1 } } }
      calls.push(config.params); if (failRuns) throw Error('runs offline'); return { data: [{ id: 1 }] }
    } } },
  })
  const state = vm.useOperationsCenter(); state.runStatus.value = 'failed'; await state.searchRuns(); state.runStatus.value = 'success'
  await state.loadDashboard({ quiet: true }); assert.deepEqual(calls.at(-1), { limit: 30, status: 'failed' })
  failRuns = true; await state.loadDashboard()
  assert.equal(state.loading.value, false); assert.equal(state.overview.value.summary.healthy_services, 1); assert.equal(state.jobRuns.value[0].id, 1)
  assert.equal(state.runsResource.isStale.value, true)
})
