// Real invoice editor with isolated in-memory API responses; no backend or native writes.
import { createApp, h, onMounted, ref } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import InvoiceManage from '../../../src/views/invoice/InvoiceManage.vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import * as clients from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { emptyInvoiceForm, normalizeHairRow } from '../../../src/views/invoice/composables/invoiceEditorState'

const state = window.invoiceGroupTest = { calls: [], saved: [], editor: null, outboundMode: 'ready' }
const clone = value => JSON.parse(JSON.stringify(value))
const contact = { contact_name: 'Alice', contact_phone: '123456', contact_email: 'alice@example.test', delivery_address: 'Test address', customer_grade: 'A' }
const customers = [{ kind: 'customer', company_id: 'complete', company_name: 'complete', option_key: 'customer:complete' }]
function line(id, groupKey, name, quantity) {
  return normalizeHairRow({
    id, group_key: groupKey, product_id: 11, sku_id: 9011, product_name: name, product_display: name,
    model: 'M1', color: '#1B', length: '18', net_weight_grams: '100g', quantity,
    standard_price: 30, customer_price: 30, price_per_piece: 30, total_price: quantity * 30,
    created_at: '2026-10-01T09:00:00',
  })
}
let groupVersion = 2
let stored = {
  ...emptyInvoiceForm(), ...contact,
  id: 7, invoice_no: 'GROUP-TEST', customer_id: 'complete', customer_name: 'complete',
  invoice_date: '2026-10-27', currency: 'USD', express_channel: 'FEDEX', status: 'ready',
  sync_status: 'synced', synced_at: '2026-10-27T09:30:00', xiaoman_order_id: 'REMOTE-7',
  edit_version: 'a'.repeat(64), item_groups_version: '1'.repeat(64),
  item_groups: [{ key: 'a', name: 'A首批', sort_order: 1 }],
  items: [line(1, 'a', 'Product A1', 5), line(2, 'a', 'Product A2', 3)],
}
const nextGroupVersion = () => (groupVersion++).toString(16).padStart(64, '0')
const envelope = (request, data) => ({ data: { code: 200, message: 'ok', data: clone(data) }, status: 200, statusText: 'OK', headers: {}, config: request })
const emptyOptions = { displays: [], models: [], colors: [], sizes: [], units: [], all_models: [], all_colors: [], all_sizes: [], all_units: [] }
const preview = {
  batch_fingerprint: 'excel-group-batch-1',
  rows: [{
    source_row: 2, status: 'passed', errors: [], warnings: [],
    normalized: { product: 'Imported B1', length: '18', color: '#1B', weight: '100g', quantity: 2, unit_price: 30 },
    matched_product: { product_id: 11, sku_id: 9011, product_name: 'Imported B1', model: 'M1' },
    standard_price: 30, customer_price: 30, price_source: 'manual',
  }],
}
function inventory(request) {
  const status = {
    1: { outbound_quantity: '5', shipped_quantity: '5', outbounds: [{ id: 'OB-1', number: 'CK-1', state: 'shipped', quantity: '5' }] },
    2: { outbound_quantity: '3', shipped_quantity: '1', outbounds: [
      { id: 'OB-2', number: 'CK-2', state: 'shipped', quantity: '1' },
      { id: 'OB-3', number: 'CK-3', state: 'generated', quantity: '2' },
    ] },
  }
  return envelope(request, {
    invoice_id: 7,
    items: stored.items.map(item => ({
      invoice_item_id: item.id, product_id: item.product_id, sku_id: item.sku_id,
      available_stock: 20, order_available_stock: 20,
      ...(state.outboundMode === 'unknown'
        ? { outbound_quantity: null, shipped_quantity: null, outbounds: [] }
        : status[item.id] || { outbound_quantity: '0', shipped_quantity: '0', outbounds: [] }),
    })),
  })
}

for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    const url = request.url
    const method = request.method
    const payload = typeof request.data === 'string' ? JSON.parse(request.data) : request.data
    state.calls.push({ method, url })
    if (url === '/invoices/7/editor-inventory') return inventory(request)
    if (url === '/invoices/7/item-groups' && method === 'patch') {
      if (payload.expected_version !== stored.edit_version) throw new Error('stale business version')
      if (payload.expected_groups_version !== stored.item_groups_version) throw new Error('stale group version')
      state.saved.push({ method, payload: clone(payload) })
      const assignments = new Map(payload.items.map(row => [row.id, row.group_key]))
      stored.item_groups = clone(payload.item_groups)
      stored.items = stored.items.map(item => ({ ...item, group_key: assignments.get(item.id) || item.group_key }))
      stored.item_groups_version = nextGroupVersion()
      return envelope(request, stored)
    }
    if (url === '/import/preview') return envelope(request, preview)
    if (url === '/invoices/7' && method === 'get') return envelope(request, stored)
    if (url === '/invoices/7' && method === 'put') {
      state.saved.push({ method, payload: clone(payload) })
      const items = payload.items.map((item, index) => ({
        ...item,
        id: item.id || 100 + index,
        total_price: Number(item.quantity || 0) * Number(item.price_per_piece || 0) + Number(item.discount_amount || 0),
      }))
      stored = { ...stored, ...clone(payload), items, id: 7, item_groups_version: nextGroupVersion() }
      return envelope(request, stored)
    }
    if (url === '/delegations/assignees') return envelope(request, { items: [{ id: 1, real_name: 'Test sales', username: 'test', okki_bound: true, okki_department_configured: true }] })
    if (url === '/customers/options') return envelope(request, { items: customers, total: 1, has_more: false, okki_bound: true })
    if (url === '/customers/contact-defaults') return envelope(request, contact)
    if (url.includes('/price/customer-rules/') || url.endsWith('/linked-sync')) return envelope(request, null)
    if (url === '/invoices/suggest-no') return envelope(request, { invoice_no: 'GROUP-NEW' })
    if (url === '/invoices/check-no') return envelope(request, { exists: false })
    if (url === '/invoices/previous-no') return envelope(request, { previous_invoice_no: null })
    if (url === '/invoices/merchandiser-options') return envelope(request, { items: [] })
    if (url === '/shipments/capabilities') return envelope(request, { enabled: true })
    if (url === '/invoices/summary') return envelope(request, { total: 0 })
    if (url.startsWith('/invoice-summary/')) return envelope(request, {})
    if (url === '/products/entry-options' || url === '/products/filter-options') return envelope(request, emptyOptions)
    if (url.endsWith('/validate') || url.endsWith('/sync')) return envelope(request, { ok: true })
    if (url === '/invoices') return envelope(request, { items: [], total: 0, has_more: false })
    throw new Error(`Unexpected fixture request ${method} ${url}`)
  }
}

const pinia = createPinia()
const app = createApp({
  setup() {
    const page = ref(null)
    onMounted(async () => {
      state.editor = page.value.$.setupState.editor
      await state.editor.openEdit(7)
    })
    return () => h(InvoiceManage, { ref: page })
  },
})
app.use(pinia)
const auth = useAuthStore()
auth.user = { id: 1, roles: ['super_admin'], permissions: [] }
auth.accessToken = 'isolated-invoice-groups'
app.use(ElementPlus)
app.component('GlassButton', GlassButton)
app.component('FilterBar', FilterBar)
app.component('ListPageStatus', ListPageStatus)
app.component('StatusBadge', StatusBadge)
registerPermissionDirectives(app)
app.directive('sticky-scrollbar', {})
app.mount('#app')
