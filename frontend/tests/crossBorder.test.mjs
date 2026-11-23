import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { accountingTime, actionsFor, issueHints, selectable, ticketQuantities } from '../src/views/cross_border/reviewPresentation.js'
const root = new URL('../', import.meta.url)
const source = await readFile(new URL('src/views/cross_border/composables/useCrossBorderReview.js', root), 'utf8')
function harness() {
  let fetcher
  let payload
  const confirmations = []
  const api = {
    detail: async hash => ({ data: { ...declaration, content_hash: hash } }),
    list: async () => ({ data: payload }), imports: async () => ({ data: { items: [] } }),
    export: async data => { api.exportBody = data; return { data: { id: 7 } } },
  }
  const ref = value => ({ value })
  const page = { list: ref([]), loading: ref(false), error: ref(null), searchForm: {}, refreshUpdate: async () => true }
  const useListPage = (fetch, options) => { fetcher = fetch; page.searchForm = options.searchForm; return page }
  const factory = new Function('ref', 'computed', 'onMounted', 'api', 'useListPage', 'confirmAction', 'promptAction', 'isFeedbackCancelled', 'msgError', 'msgSuccessText', 'selectable', 'refreshShipment', source.replace(/^import .*$/gm, '').replace('export function', 'function') + '; return useCrossBorderReview()')
  const state = factory(ref, fn => ({ get value() { return fn() } }), () => {}, api, useListPage, async (...args) => confirmations.push(args), async () => ({ value: '已核对最新DHL申报' }), () => false, error => { throw new Error(error) }, () => {}, selectable, async waybill => { api.refreshedWaybill = waybill })
  return { state, api, confirmations, async fetch(data, params = {}) { payload = data; await fetcher({ ...page.searchForm, page: 1, page_size: 20, ...params }, { isCurrent: () => true }); } }
}
const declaration = { row_type: 'declaration', content_hash: 'a', issues: [], blocking: false }
test('only eligible declarations can be selected, including explicit repeat exports', () => {
  assert.equal(selectable(declaration), true)
  for (const override of [{ blocking: true }, { excluded: true }, { voided: true }, { row_type: 'receipt' }, { row_type: 'ticket' }]) assert.equal(selectable({ ...declaration, ...override }), false)
  assert.equal(selectable({ ...declaration, exported: true }), true)
})
test('release actions reflect matching issue codes without releasing other blockers', () => {
  assert.deepEqual(actionsFor({ ...declaration, issues: [{ code: 'not_picked_up' }, { code: 'unknown_product_amount' }] }).map(item => item.action), ['confirm_shipped', 'assign_ticket', 'exclude'])
  assert.deepEqual(actionsFor({ ...declaration, exported: true }), [])
})
test('default all-ready selection covers pages and preserves a user deselection', async () => {
  const { state, fetch } = harness()
  await fetch({ items: [declaration], ready_content_hashes: ['a', 'b'], suspected_content_hashes: [], summary: {} })
  assert.deepEqual(state.selected.value, ['a', 'b'])
  state.toggleRow(declaration, false)
  await fetch({ items: [{ ...declaration, content_hash: 'b' }], ready_content_hashes: ['a', 'b'], suspected_content_hashes: [], summary: {} }, { page: 2 })
  assert.deepEqual(state.selected.value, ['b'])
  await fetch({ items: [declaration], ready_content_hashes: ['a'], summary: {} }, { q: 'new query' })
  assert.deepEqual(state.selected.value, ['a'])
})
test('ordinary export does not silently consent to repeat or changed declarations', async () => {
  const { state, api, fetch } = harness()
  await fetch({ items: [declaration], ready_content_hashes: ['a'], suspected_content_hashes: [], summary: {} })
  await state.exportFiles()
  assert.deepEqual(api.exportBody, { content_hashes: ['a'], confirm_reexport: false, confirm_suspected: false, reason: null })
})
test('suspected and repeat export capture explicit confirmation and reason', async () => {
  const { state, api, fetch, confirmations } = harness()
  await fetch({ items: [{ ...declaration, exported: true }], ready_content_hashes: [], suspected_content_hashes: ['a'], summary: {} })
  state.toggleRow({ ...declaration, exported: true }, true)
  await state.exportFiles()
  assert.equal(api.exportBody.confirm_reexport, true)
  assert.equal(api.exportBody.confirm_suspected, true)
  assert.equal(api.exportBody.reason, '已核对最新DHL申报')
  assert.match(confirmations[0][0], /再次生成/)
})
test('navigation and transports enforce permissions, authenticated downloads and both import formats', async () => {
  const navigation = await readFile(new URL('src/config/navigation.js', root), 'utf8')
  const client = await readFile(new URL('src/api/crossBorder.js', root), 'utf8')
  const view = await readFile(new URL('src/views/cross_border/CrossBorderReview.vue', root), 'utf8')
  assert.match(navigation, /path: '\/cross-border'.*permission: 'cross_border:read'/)
  assert.match(client, /responseType: 'blob'/)
  assert.match(client, /data.append\('files', file\)/)
  assert.match(view, /accept=".xls,.xlsx"/)
  assert.match(view, /v-permission="'cross_border:write'"/)
  assert.match(view, /Detail|CrossBorderDetail/)
})

test('exported suspected old declarations can be voided while keeping other mutations hidden', () => {
  assert.deepEqual(actionsFor({ ...declaration, exported: true, suspected_changed: true }).map(action => action.action), ['void'])
})
test('transport omits blank optional import and Beijing date filters', async () => {
  const text = await readFile(new URL('src/api/crossBorder.js', root), 'utf8')
  const factory = new Function('client', text.replace(/^import .*$/gm, '').replace('export const crossBorderApi', 'const crossBorderApi') + '; return crossBorderApi')
  let request
  const api = factory({ get: (path, options) => { request = options.params } })
  api.list({ import_id: '', bound_date_from: '', bound_date_to: null, q: '', page: 2 })
  assert.deepEqual(request, { page: 2 })
})

test('inspection links open authorized existing detail API on initial and changed routes', async () => {
  const text = await readFile(new URL('src/views/shipping/composables/useInspectionRecords.js', root), 'utf8')
  const route = { path: '/shipping/inspections', query: { inspection_id: '42' }, fullPath: '/shipping/inspections?inspection_id=42' }
  const watchers = []
  const calls = []
  const feedback = []
  const ref = value => ({ value })
  const watch = (getter, callback, options) => { watchers.push({ getter, callback }); if (options?.immediate) callback(getter()) }
  const factory = new Function('computed', 'reactive', 'ref', 'watch', 'useRoute', 'useRouter', 'getInspectionRecord', 'useListPage', 'msgError', text.replace(/^import .*$/gm, '').replace('export function', 'function') + '; return useInspectionRecords()')
  const state = factory(fn => ({ get value() { return fn() } }), value => value, ref, watch, () => route, () => ({}), async id => { calls.push(id); if (id === 99) { const error = new Error('403'); throw error } return { data: { id } } }, () => ({}), (...args) => feedback.push(args))
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(state.detail.value.id, 42)
  route.query.inspection_id = '43'
  watchers.at(-1).callback(watchers.at(-1).getter())
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(state.detail.value.id, 43)
  route.query.inspection_id = '../99'
  watchers.at(-1).callback(watchers.at(-1).getter())
  assert.deepEqual(calls, [42, 43])
  route.query.inspection_id = '99'
  watchers.at(-1).callback(watchers.at(-1).getter())
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(feedback.length, 1)
  assert.equal(state.detail.value, null)
})

test('same business filters retain manual selections across metric views', async () => {
  const { state, fetch } = harness()
  const data = { items: [declaration], ready_content_hashes: ['a', 'b'], summary: {} }
  await fetch(data)
  state.toggleRow(declaration, false)
  await fetch(data, { view: 'ready' })
  assert.deepEqual(state.selected.value, ['b'])
  await fetch(data, { view: 'exceptions' })
  assert.deepEqual(state.selected.value, ['b'])
})
test('DHL accounting timestamps and split quantities are readable without timezone conversion', () => {
  assert.equal(accountingTime('20261123095601'), '2026-11-23 09:56:01')
  assert.equal(accountingTime(null), '—')
  assert.deepEqual(ticketQuantities({ parts: [{ quantities: { 1: '3' }, expected: { 1: '6' } }, { quantities: { 2: '1' }, expected: { 2: '2' } }] }), { shipped: 4, total: 8 })
  assert.equal(ticketQuantities({ parts: [{ quantities: null }] }), null)
  assert.match(issueHints.amount_mismatch, /参考票/)
})
test('tracking refresh uses existing endpoint then reloads reconciliation and detail', async () => {
  const { state, api } = harness()
  await state.refreshTracking({ ...declaration, ticket: { waybill_no: 'DHL123' } })
  assert.equal(api.refreshedWaybill, 'DHL123')
  assert.equal(state.detail.value.content_hash, 'a')
  assert.equal(state.refreshingTracking.value, false)
})
test('detail gates logistics refresh on existing tracking write permission and shows human-readable data', async () => {
  const detail = await readFile(new URL('src/views/cross_border/CrossBorderDetail.vue', root), 'utf8')
  const view = await readFile(new URL('src/views/cross_border/CrossBorderReview.vue', root), 'utf8')
  assert.match(detail, /v-permission="'tracking:write'"[^>]*@click="\$emit\('refresh-tracking'/)
  for (const field of ['actor_name', 'actionLabels[item.action]', 'TRACKING_STATUS_LABELS', 'accountingTime', 'row.product_amount', 'row.fees', 'detail.split_group', 'detail.reference_ticket', 'issueHints[issue.code]']) assert.ok(detail.includes(field), field)
  assert.ok(view.includes("switchView('exceptions')"))
  assert.ok(view.includes('non_usd_source'))
})

test('invoice detail preserves full monetary values and gives truncated salesperson names a tooltip', async () => {
  const detail = await readFile(new URL('src/views/cross_border/CrossBorderDetail.vue', root), 'utf8')
  assert.match(detail, /prop="salesperson" label="业务员" min-width="120" show-overflow-tooltip/)
  assert.match(detail, /amountWidth\('total_amount', true\)/)
  assert.match(detail, /includeCurrency \? 210 : 140/)
  assert.match(detail, /class="invoice-total">\{\{ money\(row.total_amount\) \}\} \{\{ row.currency \}\}/)
  assert.match(detail, /\.invoice-total \{[^}]*white-space: nowrap/)
  assert.match(detail, /class="list-table" v-sticky-scrollbar/)
})
