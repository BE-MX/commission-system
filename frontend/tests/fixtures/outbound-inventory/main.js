// Real list and drawer, isolated adapters; no backend requests or inventory writes.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/table-actions.css'
import OutboundRecords from '../../../src/views/shipping/OutboundRecords.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import { shippingClient } from '../../../src/api/clients'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import { useAuthStore } from '../../../src/stores/auth'

const state = window.inventoryTest = { calls: [], fail: false, delay: 0 }
const rows = [
  { outbound_record_id: 'task:593', outbound_no: '翟 #261025', customer_name: 'Hidden Gem Salon', record_source: 'ark_task', outbound_state: 'waiting_stock', total_qty: 803, item_count: 11, can_print: false },
  { outbound_record_id: 'task:594', outbound_no: '镜像待同步', customer_name: 'Generated Customer', record_source: 'ark_task', outbound_state: 'awaiting_sync', can_print: false },
]
const items = [
  { product_id: '105711000041934', sku_id: '105711000042115', product_name: 'Super Double Drawn Keratin Tip Hair/18/#P2/8/1g', unit: 'Piece', line_numbers: [6], required: 100, available: 40, real_count: 500, unavailable_count: 460, shortage: 60, status: 'shortage', synced_at: '2026-10-14 08:33:31', warehouses: [{ warehouse_id: '8193514242746', available: 40, real_count: 500, synced_at: '2026-10-14 08:33:31' }] },
  { product_id: '101', sku_id: '321', product_name: 'Super Double Drawn Genius Weft/24/#5AT60/20g', line_numbers: [1, 2], required: 20, available: 159, real_count: 416, unavailable_count: 257, shortage: 0, status: 'sufficient', synced_at: '2026-10-14 08:46:29', warehouses: [] },
  { product_id: '', sku_id: '', product_name: '未映射产品', line_numbers: [12], required: 1, available: null, real_count: null, unavailable_count: null, shortage: null, status: 'unknown', synced_at: null, warehouses: [] },
]
shippingClient.defaults.adapter = async request => {
  state.calls.push({ method: request.method, url: request.url })
  if (request.method !== 'get') throw new Error('Fixture blocks every write')
  let data
  if (request.url === '/outbound-records') data = { items: rows, total: rows.length }
  else if (request.url.endsWith('/inventory')) {
    const second = request.url.includes('594')
    if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay))
    if (state.fail) throw new Error('Fixture inventory failure')
    data = { record: { ...rows[second ? 1 : 0], outbound_state: second ? 'done' : 'waiting_stock' }, warehouse_id: '8193514242746', source: 'okki_inventory_mirror', queried_at: '2026-10-14 08:50:00', items, shortage_count: 1, unknown_count: 1 }
  } else throw new Error(`Unexpected fixture request ${request.url}`)
  return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
}
const app = createApp({ render: () => h(OutboundRecords) })
app.use(createPinia())
useAuthStore().user = { id: 1, permissions: ['shipping_inspection:read'], roles: [] }
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] })
app.use(router)
app.use(ElementPlus)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
app.component('StatusBadge', StatusBadge)
app.component('FilterBar', FilterBar)
app.component('ListPageStatus', ListPageStatus)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
await router.push('/shipping/outbound')
await router.isReady()
app.mount('#app')
