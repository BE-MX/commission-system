import test from 'node:test'
import assert from 'node:assert/strict'
import { ref, reactive, nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

test('salary period filter is committed explicitly; retry and table refresh keep submitted status', async t => {
  const calls = []; let fail = false
  const { vm } = viewController(t, '../../src/views/salary/composables/useSalaryPeriods.js', 'useSalaryPeriods', { '@/api/salary': {
    listPeriods: async (params, config) => { calls.push(params); assert.equal(config.suppressToast, true); if (fail) throw Error('periods unavailable'); return { data: [{ id: 1 }] } },
  } })
  const state = vm.useSalaryPeriods(); fail = true; assert.equal(await state.fetchList(), false)
  assert.equal(state.periodsResource.hasLoaded.value, false); fail = false
  state.statusFilter.value = 'imported'; await state.search(); state.statusFilter.value = 'reviewing'; await state.fetchList()
  assert.equal(calls.at(-1).status, 'imported'); fail = true; await state.fetchList()
  assert.equal(state.list.value[0].id, 1); assert.equal(state.periodsResource.isStale.value, true)
  fail = false; await state.resetFilters(); assert.equal(calls.at(-1).status, undefined)
})

function workbench(t, overrides = {}, feedbackOverrides = {}) {
  const route = reactive({ params: { id: 1 } }), calls = [], messages = []
  const api = {
    getPeriod: async id => ({ data: { id, writable: true, status_version: 7 } }),
    listAnomalies: async id => ({ data: { items: [{ id }], blocking_count: 0 } }),
    listPeriodEvents: async id => ({ data: [{ id }] }),
    listAttendance: async (id, params, config) => { calls.push({ id, params }); assert.ok(config.signal); assert.equal(config.suppressToast, true); return { data: { items: [{ employee_id: id }], total: 1 } } },
    listImportRows: async (id, kind) => ({ data: { items: [], total: kind === 'insurance' ? 1 : 2 } }),
    updatePeriodWorkday: async (id, params) => { messages.push({ id, params }); return { data: {} } },
    ...overrides,
  }
  const { vm } = viewController(t, '../../src/views/salary/composables/useSalaryWorkbench.js', 'useSalaryWorkbench', {
    'vue-router': { useRoute: () => route }, '@/api/salary': api,
    '@/utils/feedback': { msgSuccess: text => messages.push(text), msgWarning: text => messages.push(text), ...feedbackOverrides },
  })
  return { state: vm.useSalaryWorkbench(), calls, messages, route }
}

test('salary resources settle independently; failed attendance retry keeps successful rows', async t => {
  let fail = true
  const { state } = workbench(t, { listAttendance: async () => { if (fail) throw Error('attendance unavailable'); return { data: { items: [{ employee_id: 1 }], total: 1 } } } })
  await state.refreshAll()
  assert.equal(state.period.value.id, 1); assert.equal(state.anomalies.value.items.length, 1); assert.equal(state.events.value.length, 1)
  assert.equal(state.attendanceResource.errorMessage.value, 'attendance unavailable')
  fail = false; await state.fetchAttendance(); fail = true; await state.fetchAttendance()
  assert.equal(state.attendance.value.items[0].employee_id, 1); assert.equal(state.attendanceResource.isStale.value, true)
})

test('attendance draft is isolated from mutation refresh and write success survives all failed reads', async t => {
  let fail = false
  const { state, calls, messages } = workbench(t, {
    getPeriod: async id => { if (fail) throw Error('refresh offline'); return { data: { id, writable: true, status_version: 7 } } },
    updatePeriodWorkday: async () => { fail = true; return { data: {} } },
  })
  state.attendanceKeyword.value = 'applied'; state.attendanceOnlyPending.value = true; await state.searchAttendance()
  state.attendanceKeyword.value = 'draft'; state.attendanceOnlyPending.value = false; await state.refreshAll()
  assert.equal(calls.at(-1).params.keyword, 'applied'); assert.equal(calls.at(-1).params.only_pending, true)
  state.workdayDraft.value = 0; await state.saveWorkday()
  assert.ok(messages.includes('保存')); assert.equal(state.periodResource.errorMessage.value, 'refresh offline')
  assert.equal(state.writable.value, false)
})

test('imports fail independently and switching period cancels all old scope resources', async t => {
  const old = deferred()
  const { state, route } = workbench(t, {
    listImportRows: async (id, kind) => { if (kind === 'insurance') throw Error('insurance offline'); return { data: { total: id, items: [] } } },
    listPeriodEvents: async id => id === 1 ? old.promise : { data: [{ id }] },
  })
  const initial = state.refreshAll(); await nextTick()
  route.params.id = 2; await nextTick(); await Promise.resolve(); await Promise.resolve()
  old.resolve({ data: [{ id: 1 }] }); await initial; await state.refreshAll()
  assert.equal(state.events.value[0].id, 2); assert.equal(state.period.value.id, 2)
  assert.equal(state.imports.value.fund.total, 2); assert.equal(state.importResources.insurance.errorMessage.value, 'insurance offline')
})

test('salary record search snapshot, row-version patch, null and zero survive independent refresh failure', async t => {
  const periodId = ref(1), period = ref({ writable: true, status: 'calculated', status_version: 8 }), activeTab = ref('attendance')
  const calls = [], writes = []; let fail = false
  const { vm } = viewController(t, '../../src/views/salary/composables/useSalaryRecords.js', 'useSalaryRecords', { '@/api/salary': {
    listRecords: async (id, params, config) => { calls.push({ id, params }); assert.equal(config.suppressToast, true); if (fail) throw Error('records offline'); return { data: { items: [{ id: 1, employee_id: 11, row_version: 9 }], total: 1, totals: { net: 123.456 }, truncated: true } } },
    editRecordManual: async (id, employeeId, payload) => { writes.push({ id, employeeId, payload }); fail = true; return { data: { id: 1, employee_id: 11, row_version: 10 } } },
  } })
  const state = vm.useSalaryRecords({ periodId, period, activeTab, refreshAll: async () => {} })
  state.recordsKeyword.value = 'applied'; await state.searchRecords(); state.recordsKeyword.value = 'draft'; await state.fetchRecords()
  assert.equal(calls.at(-1).params.keyword, 'applied'); assert.equal(state.records.value.totals.net, 123.456)
  assert.equal(await state.saveManual({ employee_id: 11, row_version: 9 }, 'bonus_manual', null), true)
  await Promise.resolve(); await Promise.resolve()
  assert.deepEqual(writes[0].payload, { bonus_manual: null, expected_row_version: 9 })
  assert.equal(state.records.value.items[0].row_version, 10); assert.equal(state.recordsResource.errorMessage.value, 'records offline')
  await state.saveManual({ employee_id: 11, row_version: 10 }, 'bonus_manual', 0)
  assert.equal(writes[1].payload.bonus_manual, 0)
  periodId.value = 2; await nextTick(); assert.deepEqual(state.records.value.items, [])
})

test('a lock confirmation for an earlier salary period cannot lock the newly opened period', async t => {
  const confirmation = deferred(), writes = []
  const { state, route } = workbench(t, { confirmPeriod: async (...args) => { writes.push(args); return { data: {} } } }, { confirmDanger: () => confirmation.promise })
  await state.refreshAll(); const pending = state.doStep({ endpoint: 'confirm', status: 'confirmed' })
  route.params.id = 2; await nextTick(); await state.refreshAll()
  confirmation.resolve(); await pending
  assert.deepEqual(writes, []); assert.equal(state.period.value.id, 2); assert.equal(state.stepping.value, '')
})

test('confirmation preserves the reviewed salary version, and stale period data prevents next steps', async t => {
  const confirmation = deferred(), writes = []; let fail = false
  const { state } = workbench(t, {
    getPeriod: async id => { if (fail) throw Error('period offline'); return { data: { id, writable: true, status_version: 7 } } },
    confirmPeriod: async (id, params) => { writes.push({ id, params }); return { data: {} } },
    unlockPeriod: async () => { throw Error('must not write') },
  }, { confirmDanger: () => confirmation.promise })
  await state.refreshAll(); const pending = state.doStep({ endpoint: 'confirm', status: 'confirmed' })
  state.period.value.status_version = 8; confirmation.resolve(); await pending
  assert.deepEqual(writes[0], { id: 1, params: { expected_version: 7 } })
  fail = true; await state.fetchPeriod(); await state.doStep({ endpoint: 'confirm', status: 'confirmed' })
  state.unlockReason.value = 'correct source'; await state.doUnlock(); assert.equal(writes.length, 1)
})

test('confirmed readonly salary period can still be unlocked from a successful current snapshot', async t => {
  const writes = []
  const { state } = workbench(t, {
    getPeriod: async id => ({ data: { id, writable: false, status: 'confirmed', status_version: 9 } }),
    unlockPeriod: async (id, params) => { writes.push({ id, params }); return { data: {} } },
  })
  await state.refreshAll(); assert.equal(state.writable.value, false); assert.equal(state.periodReady.value, true)
  state.unlockReason.value = 'source corrected'; await state.doUnlock()
  assert.deepEqual(writes[0], { id: 1, params: { reason: 'source corrected', expected_version: 9 } })
})

test('cancelled salary lock confirmation settles normally and releases the busy state', async t => {
  const { state } = workbench(t, {}, { confirmDanger: async () => { throw 'cancel' }, isFeedbackCancelled: error => error === 'cancel' })
  await state.refreshAll(); await state.doStep({ endpoint: 'confirm', status: 'confirmed' })
  assert.equal(state.stepping.value, '')
})
