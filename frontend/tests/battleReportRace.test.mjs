import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { computed, ref } from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { formatCalendarDate } from '../src/utils/datetime.js'
import { addDays, errorText, money } from '../src/views/battle-report/helpers.js'

// Execute the real component script and list controller, with controllable network timing.
function createHarness() {
  const source = fs.readFileSync(new URL('../src/views/battle-report/components/ReportDaily.vue', import.meta.url), 'utf8')
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg, '')
  const props = {
    report: { id: 1, start_date: '2026-09-22', end_date: '2026-09-30', members: [{ id: 1, team: 'A' }], detail_member_ids: [1] },
    team: '', selection: {},
  }
  const queue = []
  let unmount
  const deps = {
    computed, ref, onMounted: () => {}, onUnmounted: fn => { unmount = fn }, watch: () => {}, defineProps: () => props,
    battleReportApi: { orders: () => new Promise((resolve, reject) => queue.push({ resolve, reject })) },
    useListPage, currentBeijingDate: () => '2026-09-22', formatCalendarDate, addDays, errorText, money,
  }
  const state = new Function(...Object.keys(deps), `${source}\nreturn { searchOrders, list, orderMeta, orderError };`)(...Object.values(deps))
  return { state, queue, unmount: () => unmount() }
}

test('stale order failures cannot overwrite newer successful results', async () => {
  const { state, queue } = createHarness()
  const oldRequest = state.searchOrders(), latestRequest = state.searchOrders()
  queue[1].resolve({ items: [{ order_no: 'latest' }], total: 1, gmv: '100.00', issues: [] })
  await latestRequest
  queue[0].reject(new Error('stale error'))
  await oldRequest
  assert.deepEqual(state.list.value, [{ order_no: 'latest' }])
  assert.equal(state.orderMeta.value.gmv, '100.00')
  assert.equal(state.orderError.value, '')
})

test('stale order successes cannot replace the current filter summary', async () => {
  const { state, queue } = createHarness()
  const oldRequest = state.searchOrders(), latestRequest = state.searchOrders()
  queue[1].resolve({ items: [{ order_no: 'latest' }], total: 1, gmv: '100.00', issues: [] })
  await latestRequest
  queue[0].resolve({ items: [{ order_no: 'old' }], total: 1, gmv: '999.00', issues: [] })
  await oldRequest
  assert.deepEqual(state.list.value, [{ order_no: 'latest' }])
  assert.equal(state.orderMeta.value.gmv, '100.00')
})

test('order errors after unmount cannot update component state', async () => {
  const { state, queue, unmount } = createHarness()
  const pending = state.searchOrders()
  unmount()
  queue[0].reject(new Error('after unmount'))
  await pending
  assert.equal(state.orderError.value, '')
})
