// Actual Vue components with synthetic adapters; no backend or native inventory writes.
import { createApp, h, reactive } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/table-actions.css'
import OutboundRecords from '../../../src/views/shipping/OutboundRecords.vue'
import InvoiceHairTable from '../../../src/views/invoice/components/InvoiceHairTable.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import { shippingClient, invoiceClient } from '../../../src/api/clients'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import { useAuthStore } from '../../../src/stores/auth'

const state = window.replenishmentTest = reactive({ calls: [], fail: false, capacity: 10, outcome: 'waiting_stock', delay: 0 })
const rows = [{ outbound_record_id: 'task:1', outbound_no: '补货验收订单', customer_name: '测试客户',
  record_source: 'ark_task', outbound_state: 'waiting_stock', total_qty: 10, item_count: 1, can_print: false,
  stock_shortages: [{ product_name: 'Genius Weft/18/#1/20g', required: 10, available: 6, shortage: 4 }] }]
const envelope = (request, data) => ({ data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request })
shippingClient.defaults.adapter = async request => {
  state.calls.push({ method: request.method, url: request.url })
  if (request.url === '/outbound-records' && request.method === 'get') return envelope(request, { items: rows, total: 1 })
  if (request.url === '/outbound-records/task%3A1/replenishment-sync' && request.method === 'post') {
    if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay))
    if (state.fail) throw Object.assign(new Error('Synthetic supplier timeout'), { config: request })
    if (state.outcome === 'done') {
      rows[0].outbound_state = 'awaiting_sync'
      rows[0].stock_shortages = []
    }
    return envelope(request, { status: state.outcome, message: state.outcome === 'done' ? '小满出库单已生成并核验' : '已同步目标仓库实时库存，仍有明细库存不足' })
  }
  throw new Error(`Unexpected fixture request ${request.method} ${request.url}`)
}
invoiceClient.defaults.adapter = async request => {
  state.calls.push({ method: request.method, url: request.url })
  if (request.method !== 'get' || request.url !== '/invoices/1/editor-inventory') throw new Error('Unexpected invoice fixture request')
  return envelope(request, { invoice_id: 1, items: [{ invoice_item_id: 1, product_id: 1, sku_id: 11,
    available_stock: 0, order_available_stock: state.capacity, shipped_quantity: '0' }] })
}
const invoice = reactive([{ id: 1, item_type: 'stock', product_id: 1, sku_id: 11, quantity: 10,
  product_name: 'Genius Weft/18/#1/20g', product_display: 'Genius Weft', model: 'B1', color: '#1', length: '18',
  net_weight_grams: '20g', price_per_piece: 10, total_price: 100, options: {} }])
const noop = () => {}
const params = new URLSearchParams(location.search)
const app = createApp({ render: () => params.get('view') === 'invoice'
  ? h(InvoiceHairTable, { invoiceId: 1, items: invoice, entryOptions: {}, loadLineOptions: noop,
    onLineFilterChange: noop, onCustomFieldChange: noop, onPriceInput: noop,
    onLineDiscountChange: noop, updateLineTotal: noop, money: value => Number(value || 0).toFixed(2) })
  : h(OutboundRecords) })
app.use(createPinia())
useAuthStore().user = { id: 1, permissions: params.has('readOnly') ? ['shipping_inspection:read']
  : ['shipping_inspection:read', 'shipping_inspection:write', 'invoice:sync', 'invoice:write'], roles: [] }
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] })
app.use(router); app.use(ElementPlus)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
app.component('StatusBadge', StatusBadge); app.component('FilterBar', FilterBar); app.component('ListPageStatus', ListPageStatus)
registerPermissionDirectives(app); registerStickyScrollbarDirective(app)
await router.push('/shipping/outbound'); await router.isReady()
app.mount('#app')
