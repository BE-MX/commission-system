import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'
import * as money from '../src/utils/money.js'
import * as aftersales from '../src/views/aftersales/aftersalesRules.js'
import * as battle from '../src/views/battle-report/helpers.js'
import { reactive, nextTick } from 'vue'
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

test('late battle selector refresh does not restore a selection changed during the request', async t => {
  const old = deferred(); let calls = 0
  const { vm } = viewController(t, '../../src/views/battle-report/BattleReports.vue', 'loadReports,changeReport,selectedId,report', {
    './helpers': battle, '@/api/battleReport': { battleReportApi: {
      list: async () => ++calls === 1 ? { items: [{ id: 1 }, { id: 2 }] } : old.promise,
      get: async id => ({ id, members: [] }), overview: async id => ({ id }),
    } },
  })
  await vm.loadReports(); const pending = vm.loadReports()
  vm.selectedId.value = 2; await vm.changeReport()
  old.resolve({ items: [{ id: 1 }, { id: 2 }] }); await pending
  assert.equal(vm.selectedId.value, 2); assert.equal(vm.report.value.id, 2)
})

test('battle settings late save preserves original payload and cannot close a reopened A-B-A dialog', async t => {
  const old = deferred(), writes = []
  const makeReport = id => ({ id, version: 4, name: `Report ${id}`, start_date: '2026-10-01', end_date: '2026-10-14', target_deadline: '2026-10-01T23:59:59', visibility: 'activity', members: [{ ark_user_id: id, team: 'Original', is_captain: true }] })
  const props = reactive({ modelValue: false, report: makeReport(1) })
  const { vm, messages } = viewController(t, '../../src/views/battle-report/components/ReportSettings.vue', 'save,form,error,participantsResource,options', {
    '../helpers': battle, '@props': props, '@/api/battleReport': { battleReportApi: {
      participants: async () => ({ items: [] }), update: async (id, payload) => { writes.push({ id, payload }); return old.promise },
    } },
  })
  props.modelValue = true; await nextTick(); await new Promise(resolve => setImmediate(resolve))
  assert.equal(vm.options.value[0].ark_user_id, 1)
  vm.form.reason = 'Original reason'; const pending = vm.save()
  props.modelValue = false; props.report = makeReport(2); props.modelValue = true
  await nextTick(); await new Promise(resolve => setImmediate(resolve))
  assert.equal(vm.options.value[0].ark_user_id, 2)
  props.modelValue = false; props.report = makeReport(1); props.modelValue = true
  await nextTick(); await new Promise(resolve => setImmediate(resolve))
  vm.form.name = 'Reopened draft'; old.resolve({ id: 1 }); await pending
  assert.equal(writes[0].id, 1); assert.equal(writes[0].payload.version, 4)
  assert.equal(writes[0].payload.reason, 'Original reason'); assert.equal(writes[0].payload.members[0].team, 'Original')
  assert.equal(vm.form.name, 'Reopened draft'); assert.equal(props.modelValue, true)
  assert.deepEqual(messages.filter(message => typeof message === 'object'), [])
  assert.equal(vm.error.value, '')
})

test('after-sales summary distinguishes initial failure and keeps the last valid aggregate on refresh failure', async t => {
  let fail = true
  const { vm } = viewController(t, '../../src/views/aftersales/AfterSalesAnalytics.vue', 'summaryResource,data,fetchData,barScale,maxIssue', {
    '../../utils/money.js': money, './aftersalesRules': aftersales,
    '@/api/aftersales': { getAfterSalesAnalytics: async config => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (fail) throw Error('summary offline'); return { data: { total: 7, by_issue: [{ count: 4 }] } } } },
  })
  assert.equal(await vm.fetchData(), false); assert.equal(vm.data.value, null)
  fail = false; await vm.fetchData(); assert.equal(vm.barScale(2, vm.maxIssue.value), 0.5)
  fail = true; await vm.fetchData(); assert.equal(vm.data.value.total, 7); assert.equal(vm.summaryResource.isStale.value, true)
})

test('production dashboard latest aggregate wins while independent quiet/interactive loading settles', async t => {
  const old = deferred(); let count = 0, fail = false
  const { vm } = viewController(t, '../../src/views/production/composables/useDashboardData.js', 'useDashboardData', {
    '@/api/production': { getDashboardData: async config => { assert.equal(config.suppressToast, true); assert.ok(config.signal); if (fail) throw Error('dashboard offline'); if (++count === 1) return old.promise; return { orders: [{ id: 2, products: [] }], kpi: { transit_count: 2 }, process_stats: [{ name: 'Sewing' }], today_completions: [{ id: 8 }] } } },
  })
  const state = vm.useDashboardData(), pending = state.refresh(); await state.refresh()
  old.resolve({ orders: [{ id: 1 }], kpi: { transit_count: 1 } }); await pending
  assert.equal(state.orders.value[0].id, 2); assert.equal(state.kpiStats.value.transitCount, 2); assert.equal(state.loading.value, false)
  assert.equal(state.processStats.value[0].name, 'Sewing'); assert.equal(state.completedToday.value[0].id, 8)
  fail = true; await state.refresh(); assert.equal(state.orders.value[0].id, 2); assert.equal(state.dashboardResource.isStale.value, true)
})

test('battle report detail succeeds even when overview fails; overview retry retains independent detail', async t => {
  let fail = true
  const { vm } = viewController(t, '../../src/views/battle-report/BattleReports.vue', 'loadReports,loadOverview,report,overview,detailResource,overviewResource', {
    './helpers': battle, '@/api/battleReport': { battleReportApi: {
      list: async (params, config) => { assert.equal(config.suppressToast, true); return { items: [{ id: 1 }] } },
      get: async id => ({ id, members: [] }), overview: async () => { if (fail) throw Error('overview offline'); return { total: 5 } },
    } },
  })
  await vm.loadReports(); assert.equal(vm.report.value.id, 1); assert.equal(vm.overview.value, null)
  assert.equal(vm.detailResource.hasLoaded.value, true); assert.match(vm.overviewResource.errorMessage.value, /offline/)
  fail = false; await vm.loadOverview(); fail = true; await vm.loadOverview()
  assert.equal(vm.overview.value.total, 5); assert.equal(vm.overviewResource.isStale.value, true)
})

test('battle report archive scope and selected ID clear old aggregates before failure or late response', async t => {
  const old = deferred(); let failArchive = false
  const { vm } = viewController(t, '../../src/views/battle-report/BattleReports.vue', 'loadReports,changeReport,selectedId,archived,report,reports,selectorResource', {
    './helpers': battle, '@/api/battleReport': { battleReportApi: {
      list: async params => { if (params.archived && failArchive) throw Error('archive offline'); return { items: [{ id: 1 }] } },
      get: async id => id === 1 ? old.promise : { id, members: [] }, overview: async id => ({ id }),
    } },
  })
  const pending = vm.loadReports(); await new Promise(resolve => setImmediate(resolve))
  vm.selectedId.value = 2; await vm.changeReport(); old.resolve({ id: 1, members: [] }); await pending
  assert.equal(vm.report.value.id, 2)
  failArchive = true; vm.archived.value = true; await vm.loadReports()
  assert.equal(vm.report.value, null); assert.deepEqual(vm.reports.value, []); assert.equal(vm.selectorResource.hasLoaded.value, false)
})
