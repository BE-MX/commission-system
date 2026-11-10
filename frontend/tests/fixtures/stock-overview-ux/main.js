// Real stock view with synthetic in-memory data. No backend or business credentials.
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
import StockOverview from '../../../src/views/stock/StockOverview.vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import * as clients from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'

const rows = [
  {
    product_id: 101, product_name: 'Genius Weft/22/#8TP18/60/20g', model: 'B1 天才发帘',
    sales_30d: 48, sales_90d: 132, avg_daily_sales_30d: 1.6,
    enable_count: 8, free_stock: 5, real_count: 12, effective_enable_count: 5,
    free_stock_synced_at: '2026-11-09T09:30:00', production_in_transit: 15,
    stock_status: '加急中', stock_items: [{ item_id: 9001, order_no: 'PO-TEST-001', batch_no: 'B-001', order_qty: 20, received_qty: 5, in_transit_qty: 15, is_urgent: true, expected_delivery_date: '2026-11-18' }],
    safety_stock: 20, suggested_qty: 12, status: 'shortage', safety_stock_source: 'formula',
  },
  {
    product_id: 102, product_name: 'Hand Tied Weft/20/#613/18g', model: 'B2 手编发帘',
    sales_30d: 31, sales_90d: 95, avg_daily_sales_30d: 1.0,
    enable_count: 16, free_stock: 14, real_count: 20, effective_enable_count: 14,
    free_stock_synced_at: '2026-11-09T09:30:00', production_in_transit: 8,
    stock_status: '备货中', stock_items: [{ item_id: 9002, order_no: 'PO-TEST-002', batch_no: 'B-002', order_qty: 10, received_qty: 2, in_transit_qty: 8, is_urgent: false, expected_delivery_date: '2026-11-25' }],
    safety_stock: 12, suggested_qty: 4, status: 'warning', safety_stock_source: 'manual',
  },
  {
    product_id: 103, product_name: 'Tape Hair/18/#2/50g', model: 'C1 胶片发',
    sales_30d: 12, sales_90d: 44, avg_daily_sales_30d: 0.4,
    enable_count: 80, free_stock: 72, real_count: 82, effective_enable_count: 72,
    free_stock_synced_at: '2026-11-09T09:30:00', production_in_transit: 0,
    stock_status: '', stock_items: [], safety_stock: 20, suggested_qty: 0,
    status: 'sufficient', safety_stock_source: 'tft',
  },
  {
    product_id: 'local-example', product_name: 'Custom Bulk/24/Natural/100g', model: '定制散装',
    sales_30d: 0, sales_90d: 0, avg_daily_sales_30d: 0,
    enable_count: 0, free_stock: null, real_count: 0, effective_enable_count: 0,
    free_stock_synced_at: null, production_in_transit: 0,
    stock_status: '', stock_items: [], safety_stock: 0, suggested_qty: 0,
    status: 'unset', safety_stock_source: '', data_anomaly: true,
  },
]
const state = window.stockUxFixture = { calls: [], writes: [] }
const envelope = (request, data) => ({ data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request })
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    const url = request.url
    const method = request.method || 'get'
    state.calls.push({ method, url, params: request.params })
    if (url === '/overview' && method === 'get') {
      const params = request.params || {}
      let items = rows.filter(row => {
        const statuses = String(params.status || '').split(',').filter(Boolean)
        const keyword = String(params.keyword || '').toLowerCase()
        return (!statuses.length || statuses.includes(row.status))
          && (!keyword || `${row.product_name} ${row.model}`.toLowerCase().includes(keyword))
      })
      const sort = params.sort || params.sort_field
      const order = params.order || params.sort_order
      if (sort) items = [...items].sort((a, b) => ((a[sort] || 0) - (b[sort] || 0)) * (order === 'asc' || order === 'ascending' ? 1 : -1))
      const total = items.length
      const page = Number(params.page || 1)
      const pageSize = Number(params.page_size || 20)
      items = items.slice((page - 1) * pageSize, page * pageSize)
      return envelope(request, { items, total, summary: { shortage_count: 1, warning_count: 1, sufficient_count: 1, unset_count: 1 } })
    }
    if (url === '/filter-options') return envelope(request, { models: ['B1 天才发帘', 'B2 手编发帘', 'C1 胶片发'], types: ['Genius Weft', 'Hand Tied Weft', 'Tape Hair'], sizes: ['18', '20', '22', '24'], colors: ['#8TP18/60', '#613', '#2'], weights: ['18g', '20g', '50g', '100g'] })
    if (url === '/overview/101/sync-inventory' && method === 'post') {
      state.writes.push(url)
      Object.assign(rows[0], { enable_count: 25, free_stock: 25, real_count: 30, effective_enable_count: 25, suggested_qty: 0, status: 'sufficient' })
      return envelope(request, { synced: true })
    }
    if (url === '/order-products/9001/progress') return envelope(request, { completion_rate: 50, completed_steps: 1, total_steps: 2, all_completed: false, steps: [{ id: 1, step_order: 1, process_name: '备料', status: 1, completed_at: '2026-11-08 14:00', completed_by_user_name: '测试员工' }, { id: 2, step_order: 2, process_name: '质检入库', status: 0 }] })
    if (url === '/order-products/9002/progress') return envelope(request, { completion_rate: 0, completed_steps: 0, total_steps: 0, all_completed: false, steps: [] })
    if (method !== 'get') throw Error('隔离验收只允许本页明确的模拟库存同步')
    return envelope(request, { items: [], total: 0 })
  }
}
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/stock/overview', component: StockOverview },
  { path: '/production/products', component: { render: () => h('p', '产品绑定模拟页') } },
] })
const app = createApp({ render: () => h('main', { style: 'padding:24px 28px;max-width:1600px;margin:auto' }, [
  h('div', { style: 'margin-bottom:16px;display:flex;align-items:center;gap:16px' }, [h('strong', '销量备货一览'), h('span', '隔离样例 · 无真实业务写入')]),
  h(RouterView),
]) })
app.use(createPinia())
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
useAuthStore().accessToken = 'stock-isolated-fixture'
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
for (const [name, component] of Object.entries({ GlassButton, FilterBar, ListPageStatus, StatusBadge })) app.component(name, component)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
await router.push('/stock/overview')
await router.isReady()
app.mount('#app')
