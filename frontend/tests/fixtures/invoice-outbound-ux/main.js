// Real views with in-memory GET adapters. No backend, credentials or business writes.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/liquid-glass.css'
import '../../../src/styles/table-actions.css'
import InvoiceManage from '../../../src/views/invoice/InvoiceManage.vue'
import OutboundRecords from '../../../src/views/shipping/OutboundRecords.vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import * as clients from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import { emptyInvoiceForm } from '../../../src/views/invoice/composables/invoiceEditorState'

const state = window.uxFixture = { calls: [], deniedWrites: [] }
const item = { id: 1, product_kind: 'hair', product_name: 'Genius Weft/22/#8TP18/60/20g', product_display: 'Genius Weft', model: 'B1天才发帘', color: '#8TP18/60', length: '22', net_weight_grams: '20g', quantity: 10, price_per_piece: 10, standard_price: 10, discount_amount: 0, total_price: 100, product_id: '100', sku_id: '200' }
const orders = [7, 8, 9].map((id, index) => ({ ...emptyInvoiceForm(), id, invoice_no: `UX-TEST-${id}`, order_type: index === 1 ? 'presale' : 'stock', customer_name: 'Example Salon · 隔离样例', customer_id: 'test', customer_grade: 'A', currency: index === 2 ? 'EUR' : 'USD', invoice_date: '2026-10-23', created_at: '2026-10-23 09:00:00', created_by_name: '测试业务员', sales_user_id: 1, sales_user_name: '测试业务员', total_amount: index === 1 ? 100 : 115, product_amount: 100, shipping_fee: index === 1 ? 0 : 10, surcharge_amount: index === 1 ? 0 : 5, status: 'synced', sync_status: 'synced', item_count: 1, xiaoman_order_id: String(id), contact_name: 'Example', contact_phone: '000', delivery_address: 'Test address', express_channel: 'FEDEX', items: [{ ...item }] }))
const records = [
  { outbound_record_id: '101', outbound_invoice_id: '101', outbound_no: 'UX-OUT-101', customer_name: 'Example Salon', outbound_date: '2026-10-23 00:00:00', record_source: 'okki', outbound_state: 'ready', status: 'submitted', can_print: true, item_count: 1, total_qty: 10, photo_count: 2 },
  { outbound_record_id: 'task:102', outbound_no: 'UX-WAIT-102', customer_name: 'Stock Check Salon', record_source: 'ark_task', outbound_state: 'waiting_stock', can_print: false, item_count: 1, total_qty: 10 },
]
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    state.calls.push({ method: request.method, url: request.url })
    if (request.method !== 'get') { state.deniedWrites.push(request.url); throw Error('隔离验收禁止业务写入') }
    const url = request.url
    const order = orders.find(row => url.includes(`/invoices/${row.id}`)) || orders[0]
    let data = { items: [], total: 0, has_more: false }
    if (url === '/invoices') data = { items: orders, total: orders.length }
    else if (url === '/invoices/summary') data = { gmv: 230, order_count: 3, new_sign_count: 1, average_order_amount: 115, non_usd_count: 1 }
    else if (url.endsWith('/related-detail')) data = { order, checked_at: '2026-10-23 09:10:00' }
    else if (url.endsWith('/related-detail/receipts')) data = { state: 'ready', source: 'local', items: [], summary: { effective_amount: 0, total_amount: order.total_amount }, checked_at: '2026-10-23 09:10:00' }
    else if (url.endsWith('/related-detail/outbounds')) data = { state: 'ready', items: [], tasks: [], batches: [], summary: { shipped_quantity: 0, ordered_quantity: 10, by_item: {} }, checked_at: '2026-10-23 09:10:00' }
    else if (url === '/outbound-records') data = { items: records, total: records.length }
    else if (url.endsWith('/inventory')) data = { record: records[0], warehouse_name: '样例仓库', queried_at: '2026-10-23 09:10:00', shortage_count: 1, unknown_count: 1, items: [
      { product_name: item.product_name, sku_id: '200', unit: '件', line_numbers: [1], required: 10, available: 4, real_count: 14, unavailable_count: 10, shortage: 6, status: 'shortage', synced_at: '2026-10-23 09:10:00', warehouses: [] },
      { product_name: '待映射商品', sku_id: null, line_numbers: [2], required: 2, available: null, real_count: null, unavailable_count: null, shortage: null, status: 'unknown', warehouses: [] },
    ] }
    else if (url.endsWith('/print-data')) data = { record: records[0], items: [{ product_name: item.product_name, spec: item.model, qty: 10, unit: '件' }] }
    else if (url === '/shipments/capabilities') data = { enabled: true }
    else if (url.includes('/shipments/order/')) data = { items: [] }
    else if (url.endsWith('/shipment-inventory')) data = { invoice_id: order.id, source: 'okki_live', queried_at: '2026-10-23 09:10:00', items: [{ invoice_item_id: 1, product_id: '100', sku_id: '200', available_stock: '10' }] }
    else if (url === '/delegations/assignees') data.items = [{ id: 1, real_name: '测试业务员', username: 'test', okki_bound: true }]
    else if (url === '/customers/options') data = { items: [{ kind: 'customer', company_id: 'test', company_name: 'Example Salon', option_key: 'customer:test' }], total: 1, okki_bound: true }
    else if (url.endsWith('/linked-sync') || url.includes('/price/customer-rules/')) data = null
    else if (/\/invoices\/\d+$/.test(url)) data = order
    return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/invoice/manage', component: InvoiceManage }, { path: '/shipping/outbound', component: OutboundRecords },
] })
const app = createApp({ render: () => h('main', { style: 'padding:24px 28px;max-width:1440px;margin:auto' }, [
  h('nav', { style: 'display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap' }, [
    h('strong', '隔离样例 · 无真实业务写入'),
    h('button', { onClick: () => router.push('/invoice/manage') }, '订单发票'),
    h('button', { onClick: () => router.push('/shipping/outbound') }, '出库打印'),
    h('button', { onClick: () => { useAuthStore().user = { id: 1, roles: [], permissions: ['invoice:read', 'shipping_inspection:read'] } } }, '切换只读身份'),
  ]), h(RouterView),
]) })
app.use(createPinia())
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
useAuthStore().accessToken = 'isolated-fixture'
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
for (const [name, component] of Object.entries({ GlassButton, FilterBar, ListPageStatus, StatusBadge })) app.component(name, component)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
await router.push('/invoice/manage')
await router.isReady()
app.mount('#app')
