import test from 'node:test'
import assert from 'node:assert/strict'
import * as Vue from 'vue'
import { viewController } from './helpers/viewController.mjs'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import * as datetime from '../src/utils/datetime.js'

function response(total, items = []) { return { data: { total, items } } }
function deferred() {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}
function controller(t, api, permissions, clock = datetime) {
  const { vm, auth } = viewController(t, '../../src/views/dashboard/composables/useDashboardData.js', 'useDashboardData', {
    '@/composables/useAsyncResource': { useAsyncResource },
    '@/api/customer': { getSnapshotList: api.getSnapshotList },
    '@/api/commission': { getBatchList: api.getBatchList },
    '@/api/employee': { getEmployeeList: api.getEmployeeList },
    '@/api/payment': { getSyncedPayments: api.getSyncedPayments },
    '@/api/tracking': { getShipmentList: api.getShipmentList, getTrackingStats: api.getTrackingStats },
    '@/api/design': { getRequests: api.getRequests, getTaskList: api.getTaskList, getDesignStats: api.getDesignStats },
    '@/api/dashboard': { getCustomerWorkSummary: api.getCustomerWorkSummary, fetchGreeting: async () => ({ data: {} }) },
    '@/assets/daily-tips.json': { default: ['本地提醒'] },
    '../holidays': { getTodayHolidays: () => [], getUpcomingHolidays: () => [] },
    '@/utils/datetime': clock,
    '../../../utils/money.js': { formatMoney: value => String(value ?? '-') },
  })
  auth.user = { id: 7, permissions }
  Object.defineProperty(auth, 'permissions', { get: () => auth.user?.permissions || [] })
  auth.hasAnyPermission = requested => requested.some(permission => auth.permissions.includes(permission))
  const scope = Vue.effectScope()
  const dash = scope.run(() => vm.useDashboardData())
  t.after(() => scope.stop())
  return { dash, auth }
}

test('dashboard keeps successful counts and recent records when another recent source fails, then retries it', async t => {
  let commissionRecentAttempts = 0
  const { dash } = controller(t, {
    getBatchList: ({ page_size }) => {
      if (page_size === 1) return Promise.resolve(response(12, [{ id: 1, status: 'draft' }]))
      commissionRecentAttempts++
      return commissionRecentAttempts === 2
        ? Promise.resolve(response(12, [{ id: 2, batch_name: '九月批次', status: 'confirmed' }]))
        : Promise.reject(new Error('commission unavailable'))
    },
    getSyncedPayments: ({ page_size }) => Promise.resolve(response(3, page_size === 1
      ? [{ id: 8, payment_amount: 100 }] : [{ id: 8, customer_name: '客户甲', payment_amount: 100 }])),
  }, ['commission:read', 'payment:read'])
  await dash.loadAllData()
  assert.equal(dash.batchCount.value, 12)
  assert.equal(dash.recentCommissions.value.length, 0)
  assert.equal(dash.resources.recentCommissions.hasLoaded.value, false)
  assert.ok(dash.resources.recentCommissions.error.value)
  assert.equal(dash.recentPayments.value[0].customerName, '客户甲')
  await dash.resources.recentCommissions.load()
  assert.equal(dash.recentCommissions.value[0].name, '九月批次')
  assert.equal(dash.resources.recentCommissions.error.value, null)
  await dash.resources.recentCommissions.load()
  assert.equal(dash.recentCommissions.value[0].name, '九月批次')
  assert.equal(dash.resources.recentCommissions.isStale.value, true)
})

test('dashboard clears changed account or permission scope, aborts old requests, and rejects late responses', async t => {
  const first = deferred(), second = deferred(), signals = []
  const { dash, auth } = controller(t, {
    getEmployeeList: (_, config) => {
      signals.push(config.signal)
      return signals.length === 1 ? first.promise : second.promise
    },
  }, ['employee:read'])
  const oldLoad = dash.loadAllData()
  await Vue.nextTick()
  assert.equal(dash.employeeCount.value, null)
  auth.user = { id: 8, permissions: ['employee:read'] }
  assert.equal(signals[0].aborted, true)
  const newLoad = dash.loadAllData()
  second.resolve(response(2))
  await newLoad
  first.resolve(response(99))
  await oldLoad
  assert.equal(dash.employeeCount.value, 2)
  auth.user = { id: 8, permissions: [] }
  assert.equal(dash.employeeCount.value, null)
  assert.equal(dash.resources.employees.hasLoaded.value, false)
})

test('mounted logistics card distinguishes initial read failure from a real empty latest-five set and retries', async t => {
  let retries = 0
  const resource = Vue.reactive({ error: new Error('down'), hasLoaded: false, loading: false, load: () => { retries++ } })
  const data = Vue.reactive({ recentShipments: [], resources: { recentShipments: resource } })
  const icon = { ArrowRight: slotShell, Van: slotShell }
  const component = loadComponent('../../src/views/dashboard/components/LogisticsCard.vue', {
    '@/utils/datetime': datetime,
    '@element-plus/icons-vue': icon,
  })
  const mounted = mountComponent(t, component, { data }, undefined, { 'router-link': slotShell, 'el-icon': slotShell })
  assert.match(mounted.text(), /最近 5 单/)
  assert.match(mounted.text(), /读取失败/)
  assert.doesNotMatch(mounted.text(), /当前没有在途运单/)
  mounted.find(node => node.type === 'button')[0].props.onClick()
  assert.equal(retries, 1)
  resource.error = null
  resource.hasLoaded = true
  await Vue.nextTick()
  assert.match(mounted.text(), /当前没有在途运单/)
})

test('mounted overview does not present a failed recent source as an empty activity feed', async t => {
  let retries = 0
  const failed = Vue.reactive({ error: new Error('down'), hasLoaded: false, loading: false, load: () => { retries++ } })
  const idle = Vue.reactive({ error: null, hasLoaded: false, loading: false, load() {} })
  const data = Vue.reactive({
    recentCommissions: [], recentTrackings: [], recentDesigns: [], recentPayments: [],
    donutData: [], donutSegments: [], enabledResources: ['recentCommissions'],
    resources: { recentCommissions: failed, trackingStats: idle, designStats: idle },
  })
  const component = loadComponent('../../src/views/dashboard/components/OverviewPanels.vue', {
    '@element-plus/icons-vue': { ArrowRight: slotShell, DataAnalysis: slotShell, Document: slotShell },
  })
  const mounted = mountComponent(t, component, { data }, undefined, { 'router-link': slotShell, 'el-icon': slotShell })
  assert.match(mounted.text(), /提成批次读取失败/)
  assert.doesNotMatch(mounted.text(), /暂无最近动态/)
  mounted.find(node => node.type === 'button')[0].props.onClick()
  assert.equal(retries, 1)
  failed.error = null
  failed.hasLoaded = true
  await Vue.nextTick()
  assert.match(mounted.text(), /暂无最近动态/)
})

test('dashboard month and last-thirty-day boundaries use Beijing date across month rollover', async t => {
  const calls = { design: null, payments: [] }
  const clock = { ...datetime, currentBeijingDate: () => '2026-10-01' }
  const { dash } = controller(t, {
    getTaskList: () => Promise.resolve(response(0)),
    getRequests: () => Promise.resolve(response(0)),
    getDesignStats: params => { calls.design = params; return Promise.resolve({ data: { summary: { total: 0, completed: 0, in_progress: 0, scheduled: 0 } } }) },
    getSyncedPayments: params => { calls.payments.push(params); return Promise.resolve(response(0)) },
  }, ['design:manage', 'payment:read'], clock)
  await dash.loadAllData()
  assert.deepEqual(calls.design, { start_date: '2026-10-01', end_date: '2026-10-31' })
  assert.equal(calls.payments.length, 2)
  assert.ok(calls.payments.every(params => params.date_start === '2026-09-01' && params.date_end === '2026-10-01'))
})
