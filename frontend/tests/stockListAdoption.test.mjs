import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useTableSort } from '../src/composables/useTableSort.js'
import { watchListResourceScope } from '../src/composables/useListResourceScope.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail }); return { promise, resolve, reject } }
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Vue.nextTick() }
const feedback = { msgSuccessText() {}, msgWarning() {}, msgInfo() {}, msgError() {}, confirmAction: async () => {} }
const tableView = () => ({ visibleKeys: Vue.ref([]), density: Vue.ref('default'), panelRef: Vue.ref(null) })
function execute(t, path, result, modules = {}, props = {}) {
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const defaults = {
    vue: { ...Vue, onMounted() {}, onUnmounted() {} },
    'vue-router': { useRouter: () => ({}) },
    '@/composables/useListPage': { useListPage: (fn, options) => useListPage(fn, { ...options, immediate: false }) },
    '@/composables/useAsyncResource': { useAsyncResource }, '@/composables/useTableSort': { useTableSort },
    '@/composables/useListResourceScope': { watchListResourceScope }, '@/composables/useTableView': { useTableView: tableView },
    './composables/useStockOverviewTable': { useStockOverviewTable: tableView },
    './composables/useSafetyConfigTable': { useSafetyConfigTable: tableView },
    './composables/useProductionOrderTables': { useProductionOrderTables: () => ({}) },
    './composables/stockResources': { loadStockFilterOptions: async () => ({}), loadStockProgress: async () => ({}) },
    './composables/useProductionCart': { useProductionCart: () => ({ cartItems: Vue.ref([]), cartCount: Vue.ref(0), selectedCartIds: Vue.ref([]), loadCart() {} }) },
    './materialOptions': { loadMaterialOptions: async () => [] }, './safetyConfigPresentation': {},
    '@/utils/feedback': feedback, '@/utils/datetime': { currentBeijingDate: () => '2026-10-02', formatBeijingDateTime: String, formatBeijingTime: String },
    '@/stores/auth': { useAuthStore: () => ({ hasPermission: () => true }) },
  }
  let source = readFileSync(new URL(path, import.meta.url), 'utf8')
  if (path.endsWith('.vue')) source = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source = source.replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
    const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
    return `const ${declaration} = modules[${JSON.stringify(key)}] || {};`
  }).replace(/export /g, '')
  return scope.run(() => new Function('modules', 'defineProps', 'defineModel', `${source}\nreturn ${result};`)(
    { ...defaults, ...modules }, () => Vue.reactive(props), () => Vue.ref(false),
  ))
}

const resources = [
  ['stock/StockOverview', 'getStockOverview'], ['stock/SafetyConfig', 'getSafetyList'],
  ['stock/ProductionOrderManage', 'getProductionOrders', 'orderState'], ['stock/ProductionOrderManage', 'getProductionOrderItems', 'itemState'],
  ['stock/ProductionOrderPrint', 'getProductionPrintOrders'], ['stock/PublicInventory', 'getPublicInventory'],
  ['semifinished/MaterialManage', 'getMaterials'], ['semifinished/OrderManage', 'getSemifinishedOrders'], ['semifinished/InventoryManage', 'getSemifinishedInventory'],
]
for (const [file, method, binding = 'listState'] of resources) test(`${file}/${method} real adapter retries first failure and preserves submitted filters and stale rows`, async t => {
  let fail = true; const calls = []
  const payload = { items: [{ id: 11, material_id: 7, status: 0, safety_stock: 10, enable_count: 8, production_in_transit: 3 }], total: 101 }
  const state = execute(t, `../src/views/${file}.vue`, binding, { [file.startsWith('stock') ? '@/api/stock' : '@/api/semifinished']: {
    [method]: async (params, config) => { calls.push({ params, config }); if (fail) throw new Error('fixture offline'); return file.startsWith('stock') ? { data: payload } : payload },
  } })
  assert.equal(await state.fetchList(), false); assert.equal(state.errorMessage.value, 'fixture offline'); assert.equal(state.hasLoaded.value, false)
  fail = false; state.searchForm.keyword = 'submitted'; await state.handleSearch()
  state.searchForm.keyword = 'unsent'; await state.handlePageChange(2)
  assert.equal(calls.at(-1).params.keyword, 'submitted'); assert.equal(calls.at(-1).params.page, 2)
  assert.equal(calls.at(-1).config.suppressToast, true); assert.ok(calls.at(-1).config.signal instanceof AbortSignal)
  fail = true; await state.fetchList(); assert.equal(state.list.value[0].id, 11); assert.equal(state.dataPage.value, 2); assert.equal(state.isStale.value, true)
  fail = false; await state.handleSizeChange(50); assert.equal(calls.at(-1).params.page, 1); assert.equal(calls.at(-1).params.page_size, 50)
})

test('stock total summary ignores a superseded read; sorting does not submit a draft', async t => {
  const queue = [], calls = []
  const state = execute(t, '../src/views/stock/StockOverview.vue', '{ listState, summary, handleSortChange }', { '@/api/stock': { getStockOverview: (params, config) => { calls.push({ params, config }); const item = deferred(); queue.push(item); return item.promise } } })
  const old = state.listState.fetchList(); state.listState.searchForm.keyword = 'pending'
  const latest = state.handleSortChange({ prop: 'model', order: 'ascending' })
  assert.equal(calls[1].params.keyword, undefined); assert.equal(calls[1].params.sort, 'model'); assert.equal(calls[0].config.signal.aborted, true)
  queue[1].resolve({ data: { items: [{ id: 2 }], total: 1, summary: { shortage_count: 2 } } }); await latest
  queue[0].resolve({ data: { items: [{ id: 1 }], total: 1, summary: { shortage_count: 999 } } }); await old
  assert.equal(state.summary.shortage_count, 2); assert.equal(state.listState.list.value[0].id, 2)
})

test('stock reset restores original default sorting in exactly one read', async t => {
  const calls = []
  const state = execute(t, '../src/views/stock/StockOverview.vue', '{ listState, handleSortChange, resetFilters }', { '@/api/stock': { getStockOverview: async params => { calls.push(params); return { data: { items: [], total: 0 } } } } })
  state.listState.searchForm.keyword = 'fixture'; await state.listState.handleSearch()
  await state.handleSortChange({ prop: 'model', order: 'ascending' })
  const count = calls.length; await state.resetFilters()
  assert.equal(calls.length, count + 1); assert.equal(calls.at(-1).sort, 'sales_30d'); assert.equal(calls.at(-1).order, 'desc'); assert.equal(calls.at(-1).keyword, undefined)
})

test('safety adapter retains existing calculation and refuses late AI preview on another page', async t => {
  const ai = deferred()
  const state = execute(t, '../src/views/stock/SafetyConfig.vue', '{ listState, aiBatchGenerate, tableData }', { '@/api/stock': {
    getSafetyList: async () => ({ data: { items: [{ product_id: 3, safety_stock: 10, enable_count: 8, production_in_transit: 3 }], total: 1 } }), autoGenerateSafety: () => ai.promise,
  } })
  await state.listState.fetchList(); assert.equal(state.tableData.value[0].suggested_qty, 9)
  const pending = state.aiBatchGenerate(); await state.listState.fetchList()
  ai.resolve({ data: { items: [{ product_id: 3, suggested_safety_stock: 900 }] } }); await pending
  assert.equal(state.tableData.value[0].safety_stock, 10); assert.equal(state.tableData.value[0]._dirty, false)
})

test('material tab scope clears old rows and selection, retry stays on mappings', async t => {
  let fail = false
  const state = execute(t, '../src/views/semifinished/MaterialManage.vue', '{ listState, activeTab, changeTab, selectedMaterials }', { '@/api/semifinished': {
    getMaterials: async () => ({ items: [{ id: 1 }], total: 1 }), getMappings: async () => { if (fail) throw new Error('mapping offline'); return { items: [{ id: 2 }], total: 1 } },
  } })
  await state.listState.fetchList(); state.selectedMaterials.value = [{ id: 1 }]; fail = true; state.activeTab.value = 'mappings'; await state.changeTab()
  assert.deepEqual(state.listState.list.value, []); assert.deepEqual(state.selectedMaterials.value, []); assert.equal(state.listState.errorMessage.value, 'mapping offline')
  fail = false; await state.listState.fetchList(); assert.equal(state.listState.list.value[0].id, 2)
})

test('inventory ledger uses material scope, paging and late guard independently of adjustment material', async t => {
  const queue = [], calls = []
  const state = execute(t, '../src/views/semifinished/InventoryManage.vue', '{ ledgerState, openLedger, openAdjust, ledgerMaterial }', { '@/api/semifinished': { getInventoryLedger: (id, params, config) => { calls.push({ id, params, config }); const request = deferred(); queue.push(request); return request.promise } } })
  const first = state.openLedger({ material_id: 1 }), latest = state.openLedger({ material_id: 2 })
  queue[1].resolve({ items: [{ id: 'material2' }], total: 60 }); await latest
  queue[0].resolve({ items: [{ id: 'material1' }], total: 30 }); await first
  state.openAdjust({ material_id: 3 }); assert.equal(state.ledgerMaterial.value.material_id, 2)
  const paged = state.ledgerState.handlePageChange(2); assert.equal(calls[2].id, 2); assert.equal(calls[2].params.page, 2)
  queue[2].reject(new Error('ledger offline')); await paged
  assert.equal(state.ledgerState.list.value[0].id, 'material2'); assert.equal(state.ledgerState.dataPage.value, 1)
})

test('production delete repairs last page, retains query and refreshes affected order aggregate', async t => {
  const calls = []; let deleted = false
  const state = execute(t, '../src/views/stock/ProductionOrderManage.vue', '{ orderState, itemState, deleteOrder, deleteItem }', { '@/api/stock': {
    getProductionOrders: async params => { calls.push(['order', params]); return { data: { items: [{ id: 1 }], total: deleted ? 20 : 21 } } },
    getProductionOrderItems: async params => { calls.push(['item', params]); return { data: { items: [{ id: 1 }], total: 20 } } },
    deleteProductionOrder: async () => { deleted = true }, deleteProductionOrderItem: async () => {},
  } })
  state.orderState.searchForm.keyword = 'submitted'; await state.orderState.handleSearch(); await state.orderState.handlePageChange(2)
  state.orderState.searchForm.keyword = 'draft'; await state.deleteOrder({ id: 1, order_no: 'fixture' }); await flush()
  assert.equal(state.orderState.page.value, 1); assert.equal(calls.at(-1)[1].keyword, 'submitted')
  await state.deleteItem({ id: 1, product_name: 'fixture' }); await flush(); assert.ok(calls.some(([type]) => type === 'item'))
})

test('print categories failure is retryable and late reads do not decorate replacement rows', async t => {
  const queue = []
  const state = execute(t, '../src/views/stock/ProductionOrderPrint.vue', '{ listState, loadCategories }', { '@/api/stock': {
    getProductionPrintOrders: async () => ({ data: { items: [{ id: 1 }], total: 1 } }), getOrderPrintCategories: () => { const item = deferred(); queue.push(item); return item.promise },
  } })
  await state.listState.fetchList(); const row = state.listState.list.value[0]
  let pending = state.loadCategories(row); queue[0].reject(new Error('categories unavailable')); await pending
  assert.equal(row._categoriesError, 'categories unavailable'); assert.equal(row._categories, null)
  pending = state.loadCategories(row); await state.listState.fetchList(); queue[1].resolve({ data: { categories: [{ category_index: 3 }] } }); await pending
  assert.equal(state.listState.list.value[0]._categories, null)
  const latest = state.listState.list.value[0]; pending = state.loadCategories(latest); queue[2].resolve({ data: { categories: [{ category_index: 4 }] } }); await pending
  assert.equal(latest._categories[0].category_index, 4)
})

test('successful print logging refreshes the submitted unprinted query and repairs its last page', async t => {
  let printed = false; const calls = []
  const state = execute(t, '../src/views/stock/ProductionOrderPrint.vue', '{ listState, recordPrintLog, expandedRows }', { '@/api/stock': {
    getProductionPrintOrders: async params => { calls.push(params); return { data: { items: [{ id: 1 }], total: printed ? 20 : 21 } } },
    createProductionPrintJob: async () => { printed = true; return { data: { printed_at: '2026-10-02' } } },
  } })
  state.listState.searchForm.print_state = 'unprinted'; await state.listState.handleSearch(); await state.listState.handlePageChange(2)
  state.listState.searchForm.print_state = 'today'; state.expandedRows.value = [1]
  await state.recordPrintLog(state.listState.list.value[0], 'order')
  assert.equal(state.listState.page.value, 1); assert.equal(calls.at(-1).print_state, 'unprinted'); assert.deepEqual(state.expandedRows.value, [])
})

test('production process reset clears previously displayed progress cache and reloads current detail', async t => {
  let reads = 0
  const state = execute(t, '../src/views/stock/ProductionOrderManage.vue', '{ viewOrderDetail, handleResetProcess, progressData, currentOrder }', { '@/api/stock': {
    getProductionOrderDetail: async id => { reads++; return { data: { id, items: [] } } }, resetOrderProcess: async () => ({ data: { success: 1, total: 1 } }),
  } })
  await state.viewOrderDetail({ id: 1 }); state.progressData.value = { 9: { steps: ['old route'] } }
  await state.handleResetProcess({ id: 1, order_no: 'fixture' }); await flush()
  assert.deepEqual(state.progressData.value, {}); assert.equal(reads, 2); assert.equal(state.currentOrder.value.id, 1)
})

test('daily date scope clears previous report, 404 is empty and network failure retries submitted date', async t => {
  const calls = []; let mode = 'success'
  const state = execute(t, '../src/views/stock/DailyReport.vue', '{ selectedDate, appliedDate, reportResource, loadData }', { '@/api/stock': { getDailyReportByDate: async date => { calls.push(date); if (mode !== 'success') { const error = new Error('report offline'); error.response = { status: mode === 'missing' ? 404 : 503 }; throw error } return { data: { report_date: date } } } } })
  await state.loadData(); assert.equal(state.reportResource.data.value.report_date, '2026-10-02')
  mode = 'offline'; state.selectedDate.value = '2026-10-01'; await state.loadData(); assert.equal(state.reportResource.data.value, null); assert.equal(state.reportResource.errorMessage.value, 'report offline')
  state.selectedDate.value = '2026-09-30'; mode = 'success'; await state.reportResource.load(); assert.equal(calls.at(-1), '2026-10-01')
  mode = 'missing'; await state.loadData(); assert.equal(state.reportResource.error.value, null); assert.equal(state.reportResource.data.value, null)
})

test('material selector reads every server page and stops pagination after supersession', async t => {
  const calls = []; let current = true
  const loader = execute(t, '../src/views/semifinished/materialOptions.js', 'loadMaterialOptions', { '@/api/semifinished': { getMaterials: async (params, config) => { calls.push({ params, config }); if (params.page === 2) current = false; return { items: [{ id: params.page }], total: 301 } } } })
  const signal = new AbortController().signal
  const result = await loader({ signal, isCurrent: () => current })
  assert.deepEqual(result.map(row => row.id), [1, 2]); assert.equal(calls.length, 2); assert.equal(calls[0].config.signal, signal)
})

test('progress read initializes only a 404 and never an expired scope or server failure', async t => {
  let mode = 503, current = true, initialized = 0
  const loader = execute(t, '../src/views/stock/composables/stockResources.js', 'loadStockProgress', { '@/api/production': {
    getProgress: async () => { if (mode) { const error = new Error('progress failed'); error.response = { status: mode }; throw error } return { steps: [] } },
    initProgress: async () => { initialized++; mode = 0 },
  } })
  const context = { signal: new AbortController().signal, isCurrent: () => current }
  await assert.rejects(loader(1, context), /progress failed/); assert.equal(initialized, 0)
  mode = 404; current = false; assert.equal(await loader(1, context), null); assert.equal(initialized, 0)
  current = true; assert.deepEqual(await loader(1, context), { steps: [] }); assert.equal(initialized, 1)
})

test('cart read retains selectable data on error and reconciles selection only after a current successful reload', async t => {
  let fail = false, ids = [1, 2]
  const factory = execute(t, '../src/views/stock/composables/useProductionCart.js', 'useProductionCart', { '@/api/stock': { getProductionCart: async () => { if (fail) throw new Error('cart offline'); return { data: { items: ids.map(id => ({ id })), count: ids.length } } } } })
  const state = factory(); await state.loadCart(); state.selectedCartIds.value = [1, 2]; fail = true; await state.loadCart()
  assert.equal(state.cartErrorMessage.value, 'cart offline'); assert.equal(state.cartItems.value.length, 2); assert.deepEqual(state.selectedCartIds.value, [1, 2])
  fail = false; ids = [2]; await state.loadCart(); await flush(); assert.deepEqual(state.selectedCartIds.value, [2])
})

test('semifinished quote retries failed reads and ignores disabled or changed product scopes', async t => {
  const queue = []
  const props = Vue.reactive({ row: { product_id: 1 }, addToCart: async () => true })
  const state = execute(t, '../src/views/stock/components/ProductionOrderDialog.vue', '{ visible, form, loadQuote, toggleSemifinished, error, loading }', { '@/api/semifinished': { quoteSemifinished: () => { const item = deferred(); queue.push(item); return item.promise } } }, props)
  state.visible.value = true; await flush(); state.form.semifinished_enabled = true
  let pending = state.loadQuote(); queue[0].reject(new Error('quote offline')); await pending; assert.equal(state.error.value, 'quote offline')
  pending = state.loadQuote(); queue[1].resolve({ items: [{ material_id: 9, suggested_qty_grams: '12.5' }] }); await pending
  assert.equal(state.form.semifinished_items[0].quantity_grams, 12.5)
  pending = state.loadQuote(); state.form.semifinished_enabled = false; state.toggleSemifinished(false); queue[2].resolve({ items: [{ material_id: 99, suggested_qty_grams: 900 }] }); await pending
  assert.deepEqual(state.form.semifinished_items, []); assert.equal(state.loading.value, false)
  state.form.semifinished_enabled = true; pending = state.loadQuote(); props.row = { product_id: 2 }; await flush(); queue[3].resolve({ items: [{ material_id: 98, suggested_qty_grams: 900 }] }); await pending
  assert.deepEqual(state.form.semifinished_items, []); assert.equal(state.loading.value, false)
})

test('semifinished detail race retains the new order and mutation create returns to page one', async t => {
  const queue = [], calls = []
  const state = execute(t, '../src/views/semifinished/OrderManage.vue', '{ listState, detailResource, openDetail, createForm, submitCreate }', { '@/api/semifinished': {
    getSemifinishedOrder: () => { const item = deferred(); queue.push(item); return item.promise }, createSemifinishedOrder: async () => {},
    getSemifinishedOrders: async params => { calls.push(params); return { items: [{ id: 1 }], total: 80 } },
  } })
  const old = state.openDetail({ id: 1 }), latest = state.openDetail({ id: 2 }); queue[1].resolve({ id: 2, items: [] }); await latest; queue[0].resolve({ id: 1, items: [] }); await old
  assert.equal(state.detailResource.data.value.id, 2)
  await state.listState.handlePageChange(3); state.createForm.items = [{ material_id: 1, quantity_grams: 100 }]; await state.submitCreate(); await flush()
  assert.equal(calls.at(-1).page, 1)
})

test('all stock and semifinished read wrappers forward independent signal and suppressToast config', async t => {
  const stockMethods = [['getPublicInventory', [{}]], ['getStockOverview', [{}]], ['getSafetyList', [{}]], ['getProductionOrders', [{}]], ['getProductionOrderItems', [{}]], ['getProductionPrintOrders', [{}]], ['getFilterOptions', []], ['getLatestDailyReport', []], ['getDailyReportByDate', ['2026-10-02']], ['getProductionCart', []], ['getProductionOrderDetail', [1]], ['getOrderPrintCategories', [1]], ['queryInTransit', [[1]]], ['queryStockStatus', [[1]]]]
  const semiMethods = [['getMaterials', [{}]], ['getMappings', [{}]], ['getSemifinishedOrders', [{}]], ['getSemifinishedInventory', [{}]], ['getInventoryLedger', [1, {}]], ['getSemifinishedOrder', [1]], ['previewMaterialSync', []], ['quoteSemifinished', [{}]]]
  for (const [file, names, module] of [['stock', stockMethods, '@/api/stock'], ['semifinished', semiMethods, '@/api/semifinished']]) {
    const calls = [], client = { get: async (...args) => { calls.push(args); return { data: {} } }, post: async (...args) => { calls.push(args); return { data: {} } } }
    const api = execute(t, `../src/api/${file}.js`, `{ ${names.map(([name]) => name).join(',')} }`, { './clients': { stockClient: client, publicStockClient: client, semifinishedClient: client } })
    const config = { signal: new AbortController().signal, suppressToast: true, params: { wrong: true } }
    for (const [name, args] of names) { await api[name](...args, config); const actual = calls.at(-1).at(-1); assert.equal(actual.signal, config.signal, name); assert.equal(actual.suppressToast, true, name); if (args[0] && typeof args[0] === 'object' && !Array.isArray(args[0]) && name !== 'quoteSemifinished') assert.equal(actual.params, args[0], name) }
  }
})

test('mounted inventory empty slot renders first failure and retry, then retains table rows on refresh failure', async t => {
  let fail = true
  const listStatus = loadComponent('../../src/components/ListPageStatus.vue', { '@element-plus/icons-vue': {}, './GlassButton.vue': { default: slotShell } })
  const inventory = loadComponent('../../src/views/semifinished/InventoryManage.vue', {
    vue: { ...Vue, resolveDirective: () => ({}) },
    '@/utils/feedback': feedback, '@element-plus/icons-vue': {}, '@/components/TableTools.vue': { default: { setup: (_, { emit }) => () => Vue.h('button', { onClick: () => emit('refresh') }, 'fixture refresh') } },
    '@/composables/useTableView': { useTableView: tableView }, '@/composables/useListPage': { useListPage }, '@/composables/useAsyncResource': { useAsyncResource }, '@/composables/useListResourceScope': { watchListResourceScope },
    '@/api/semifinished': { getSemifinishedInventory: async () => { if (fail) throw new Error('mounted offline'); return { items: [{ id: 1, size: 'fixture', material_code: 'fixture' }], total: 1 } } },
  })
  const table = { props: ['data'], setup: (props, { slots }) => () => Vue.h('div', {}, props.data?.length ? props.data.map(row => Vue.h('p', row.size)) : slots.empty?.()) }
  const mounted = mountComponent(t, inventory, {}, undefined, { StatusBadge: slotShell, 'el-button': slotShell, FilterBar: slotShell, ListPageStatus: listStatus, GlassButton: slotShell, 'el-alert': slotShell, 'el-table': table, 'el-table-column': slotShell, 'el-empty': slotShell, 'el-input': slotShell, 'el-pagination': slotShell, DetailDrawer: slotShell, 'el-dialog': slotShell, 'el-form': slotShell, 'el-form-item': slotShell, 'el-input-number': slotShell })
  await flush(); assert.match(mounted.text(), /mounted offline/); assert.match(mounted.text(), /重试加载/)
  fail = false; const retry = mounted.find(node => node.props?.onClick && /重试加载/.test((node.children || []).map(child => child.text || '').join('')))[0]
  assert.ok(retry); await retry.props.onClick(); await flush(); assert.match(mounted.text(), /fixture/); fail = true; mounted.find(node => node.type === 'button' && node.text === 'fixture refresh')[0].props.onClick(); await flush(); assert.match(mounted.text(), /fixture/); assert.match(mounted.text(), /mounted offline/)
})
