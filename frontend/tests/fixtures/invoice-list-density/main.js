// Synthetic data only: the real layout and invoice page, with all clients in memory.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as Icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/liquid-glass.css'
import '../../../src/styles/kimi-design.css'
import '../../../src/styles/dashboard-theme.css'
import '../../../src/styles/table-actions.css'
import MainLayout from '../../../src/views/layout/MainLayout.vue'
import InvoiceManage from '../../../src/views/invoice/InvoiceManage.vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import ResponsiveDescriptions from '../../../src/components/ResponsiveDescriptions.vue'
import EmptyState from '../../../src/components/EmptyState.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import DetailDrawer from '../../../src/components/DetailDrawer.vue'
import * as clients from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerSortableTables } from '../../../src/components/SortableTableColumn'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'

const entries = [
  ['TEST-1104', 'Example Salon', 'stock', 'synced', 'synced'],
  ['生产测试-1104', '测试客户', 'production', 'synced', 'synced'],
  ['预售-1104', 'Example Europe', 'presale', 'synced', 'synced'],
  ['客户发票编号特别长用于测试中文和English-Long-Invoice-20261104', 'A Very Long Synthetic Customer Company Name 国际测试有限公司', 'stock', 'synced', 'synced', 'EUR'],
  ['待核对-1104', 'Sample One', 'stock', 'sync_uncertain', 'sync_uncertain'],
  ['取消-1104', 'Sample Two', 'stock', 'cancelled', 'synced'],
  ['本地-1104', 'Local Example', 'stock', 'draft', 'not_synced', 'USD', 'local'],
  ['异常-1104', 'Example Three', 'production', 'synced', 'synced', 'USD', null, true],
  ['TEST-1105', 'Sample Four', 'stock', 'sync_failed', 'sync_failed'],
  ['TEST-1106', 'Sample Five', 'production', 'synced', 'synced'],
]
// Preview-only mock contract: one model per item row (including accessories),
// total_quantity sums quantities; received_amount is fabricated, not a live projection.
const rows = entries.map(([invoice_no, customer_name, order_type, status, sync_status, currency = 'USD', transaction_route, anomaly], index) => {
  const items = [{ kind:'hair', quantity:2 }, { kind:'hair', quantity:3 }, { kind:'accessory', quantity:4 }]
  const total_amount = index === 4 ? 0.3 : currency === 'EUR' ? 99999999.99 : 1296.29
  const received_amount = [1296.29, 1400, 0, null, 0.1 + 0.2, 0, 700, 1296.29, 20, 1296.29][index]
  return { id: index + 1, invoice_no, customer_name, order_type, status, sync_status, currency,
    transaction_route: transaction_route || 'legacy', transaction_mode: transaction_route || 'legacy',
    commerce_status: 'draft', invoice_date: '2026-11-04', items,
    item_count: items.length, total_quantity: items.reduce((sum, item) => sum + item.quantity, 0),
    order_amount: index === 4 ? 0.3 : currency === 'EUR' ? 99999999.99 : 1234.56,
    total_amount, received_amount, created_by_name: '测试人员', created_at: '2026-11-04T15:46:00',
    anomalies: anomaly ? ['order', 'outbound', 'receipt'] : [],
  }
})
const state = window.invoiceDensityTest = { requests: [], writes: [] }
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    state.requests.push({ url: request.url, method: request.method, params: request.params })
    if (request.method !== 'get') {
      state.writes.push({ url: request.url, method: request.method })
      throw new Error(`Fixture rejects writes: ${request.method} ${request.url}`)
    }
    let data = { items: [], total: 0, has_more: false }
    if (request.url === '/invoices') data = { items: rows, total: rows.length }
    else if (request.url === '/invoices/summary') data = { gmv: 12345.67, new_sign_count: 2, order_count: rows.length, average_order_amount: 1234.56 }
    else if (request.url === '/shipments/capabilities') data = { enabled: true }
    else if (request.url === '/navigation-config/effective') data = { nodes: [] }
    else if (request.url === '/customer-requests/pending-count') data = { count: 0 }
    return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: MainLayout, children: [{ path: '/invoice/manage', name: 'InvoiceManage', component: InvoiceManage, meta: { title: '订单发票管理' } }] },
] })
state.route = () => router.currentRoute.value.fullPath
const app = createApp({ render: () => h(RouterView) })
for (const [key, component] of Object.entries(Icons)) app.component(key, component)
for (const component of [GlassButton, StatusBadge, ResponsiveDescriptions, EmptyState, FilterBar, ListPageStatus, DetailDrawer]) app.component(component.__name || component.name, component)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
app.use(createPinia())
const auth = useAuthStore()
auth.user = { id: 1, real_name: '测试用户', roles: ['super_admin'], permissions: [] }
auth.accessToken = 'synthetic-fixture-only'
app.use(ElementPlus, { locale: zhCn })
registerSortableTables(app)
app.use(router)
await router.push('/invoice/manage')
await router.isReady()
app.mount('#app')
