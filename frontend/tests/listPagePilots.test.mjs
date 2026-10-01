import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import * as filters from '../src/views/domestic/composables/useDomesticOrderFilters.js'

function controller(path, name, api) {
  const messages = []
  const route = Vue.reactive({ name: 'DomesticOrders', query: {} })
  const disposers = []
  const modules = {
    vue: { ...Vue, onMounted() {}, onUnmounted() {}, watch: (...args) => { const stop = Vue.watch(...args); disposers.push(stop); return stop } },
    'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) },
    'element-plus': { ElMessage: { warning() {}, success() {} }, ElMessageBox: { confirm: async () => {} } },
    '@/composables/useListPage': { useListPage: (fn, options) => useListPage(fn, { ...options, immediate: false }) },
    '@/composables/useTableView': { useTableView: () => ({}) },
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, hasPermission: () => true }) },
    '@/utils/feedback': { confirmDanger: async () => {}, confirmAction: async () => {}, promptAction: async () => ({ value: 'reason' }), msgWarning() {}, msgInfo() {}, msgSuccessText: value => messages.push(value), msgSuccess: value => messages.push(value), msgError() {} },
    '@/utils/datetime': { currentBeijingDate: () => '2026-10-01', currentBeijingDateTime: () => '2026-10-01T10:00:00' },
    '@/utils/money': { formatMoney: String }, '@/utils/download': {},
    '@/views/domestic/conditionalRouting': {}, './domesticMemberPricing': {},
    './useDomesticOrderFilters': filters,
    './invoiceSyncFlow': {}, './invoiceDateTime': {},
    '@/api/invoice': api, '@/api/receipt': api, '@/api/domestic': api,
  }
  const code = readFileSync(new URL(path, import.meta.url), 'utf8')
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
      if (key.endsWith('/money.js')) modules[key] = { formatMoney: String }
      const declaration = binding.trim().startsWith('*') ? binding.trim().replace('* as ', '')
        : binding.replace(/\bas\b/g, ':')
      return `const ${declaration} = modules[${JSON.stringify(key)}];`
    }).replace(/export /g, '')
  return { state: new Function('modules', `${code}\nreturn ${name}();`)(modules), messages, route, dispose: () => disposers.forEach(stop => stop()) }
}
const rows = (total = 61) => ({ items: [{ id: 61 }], total })
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { resolve, promise }
}

test('invoice controller keeps applied filters and page after edits; create and delete follow server sorting', async () => {
  const calls = []; let total = 61
  const { state } = controller('../src/views/invoice/composables/useInvoiceManagePage.js', 'useInvoiceManagePage', {
    listInvoices: async params => { calls.push(structuredClone(params)); return rows(total) },
    getInvoiceSummary: async () => ({}), deleteInvoice: async () => { total = 60 },
  })
  state.filters.keyword = 'applied'; await state.handleSearch()
  await state.handlePageChange(4)
  state.filters.keyword = 'draft'; await state.handleSaved()
  assert.equal(calls.at(-1).page, 4)
  assert.equal(calls.at(-1).keyword, 'applied')
  await state.removeInvoice({ id: 61 })
  assert.deepEqual(calls.slice(-2).map(call => call.page), [4, 3])
  await state.handleSaved({ created: true })
  assert.equal(calls.at(-1).page, 1)
  assert.equal(calls.at(-1).keyword, 'applied')
})

test('receipt dates and delivery flags follow only the latest submitted query', async () => {
  const calls = [], pending = []
  const { state } = controller('../src/views/receipt/useReceipts.js', 'useReceipts', {
    listReceipts: params => { calls.push(params); const request = deferred(); pending.push(request); return request.promise },
  })
  state.dates.value = ['2026-09-01', '2026-09-30']
  const first = state.handleSearch()
  state.dates.value[0] = '2026-08-01'
  const second = state.handlePageChange(2)
  assert.equal(calls[1].date_from, '2026-09-01')
  pending[1].resolve({ ...rows(), delivery_enabled: true, presale_delivery_enabled: false }); await second
  pending[0].resolve({ ...rows(9), delivery_enabled: false, presale_delivery_enabled: true }); await first
  assert.equal(state.total.value, 61)
  assert.equal(state.deliveryEnabled.value, true)
  assert.equal(state.presaleDeliveryEnabled.value, false)
})

for (const editing of [false, true]) {
  test(`successful receipt ${editing ? 'edit' : 'create'} survives a failed follow-up list read`, async () => {
    const writes = [], calls = []
    const saved = { id: 99, status: 'active', sync_status: 'pending', invoice_id: 5, amount: 10,
      collection_date: '2026-10-01', payment_type: 'bank', bank_charge: 0, attachments: [{ id: 1 }], version: 2 }
    const { state, messages } = controller('../src/views/receipt/useReceipts.js', 'useReceipts', {
      listReceipts: async params => { calls.push(params); throw new Error('list unavailable') },
      getReceiptOrders: async () => ({ items: [{ id: 5 }] }),
      getReceiptBalance: async () => ({ remaining_amount: 100, version: 1 }),
      createReceipt: async payload => { writes.push(payload); return saved },
      updateReceipt: async (id, payload) => { writes.push({ id, ...payload }); return saved },
    })
    if (editing) { state.detail.value = saved; state.editCurrent() }
    else { await state.openCreate(5); Object.assign(state.form, { amount: 10, payment_type: 'bank', attachment_ids: [1] }) }
    state.page.value = 3
    await state.submit()
    assert.equal(writes.length, 1)
    assert.equal(calls.at(-1).page, editing ? 3 : 1)
    assert.equal(state.error.value, '')
    assert.equal(state.listErrorMessage.value, 'list unavailable')
    assert.equal(state.editorVisible.value, false)
    assert.equal(state.detail.value.id, 99)
    assert.equal(messages.length, 1)
  })
}

test('domestic detail failure cannot block post-mutation list refresh; delete corrects the last page', async () => {
  const calls = []; let total = 61
  const { state } = controller('../src/views/domestic/composables/useDomesticOrders.js', 'useDomesticOrders', {
    listOrders: async params => { calls.push(params); return { data: rows(total) } },
    getOrder: async () => { throw new Error('detail unavailable') }, deleteOrder: async () => { total = 60 },
  })
  state.searchForm.customer_name = 'applied'; await state.handleSearch()
  await state.handlePageChange(4)
  state.searchForm.customer_name = 'draft'; state.detail.value = { id: 61 }
  assert.equal(await state.refreshAll(), true)
  assert.equal(calls.at(-1).page, 4)
  assert.equal(calls.at(-1).customer_name, 'applied')
  assert.equal(state.detailLoading.value, false)
  await state.handleDelete({ id: 61 })
  assert.deepEqual(calls.slice(-2).map(call => call.page), [4, 3])
  assert.equal(state.detailVisible.value, false)
})

test('cached domestic list locates a newly created order, while an ordinary tab return preserves its page', async t => {
  const calls = []
  const { state, route, dispose } = controller('../src/views/domestic/composables/useDomesticOrders.js', 'useDomesticOrders', {
    listOrders: async params => { calls.push(params); return { data: rows() } },
  })
  t.after(dispose)
  await state.handlePageChange(3)
  state.searchForm.customer_name = 'draft'
  route.name = 'DomesticOrderCreate'; route.query = {}; await Vue.nextTick()
  route.name = 'DomesticOrders'; await Vue.nextTick()
  assert.equal(calls.length, 1)
  assert.equal(state.page.value, 3)
  route.name = 'DomesticOrderCreate'; await Vue.nextTick()
  route.name = 'DomesticOrders'; route.query = { keyword: 'DO-new', order_kind: 'business' }
  await Vue.nextTick(); await Vue.nextTick()
  assert.equal(calls.length, 2)
  assert.equal(calls.at(-1).page, 1)
  assert.equal(calls.at(-1).keyword, 'DO-new')
  assert.equal(calls.at(-1).order_kind, 'business')
  assert.equal(calls.at(-1).customer_name, undefined)
  assert.equal(state.hasPendingSearch.value, false)
})
