import { createApp, h, onMounted, ref } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/liquid-glass.css'
import '../../../src/styles/kimi-design.css'
import '../../../src/styles/dashboard-theme.css'
import '../../../src/styles/app.css'
import Customers from '../../../src/views/domestic/DomesticCustomers.vue'
import Requests from '../../../src/views/domestic/DomesticCustomerRequests.vue'
import * as clients from '../../../src/api/clients'
import * as Icons from '@element-plus/icons-vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import DetailDrawer from '../../../src/components/DetailDrawer.vue'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'

const customer = { id: 42, shop_name: '隔离测试客户', balance: 100, owner_user_id: 1, status: 1 }
const requestRow = { id: 71, customer_name: customer.shop_name, request_type: 'recharge', status: 'withdrawn', created_by: 1, amount: 150 }
const state = window.rechargeTest = { requests: [], posts: [], page: null, customer, requestRow }
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    state.requests.push(`${request.method} ${request.url}`)
    let data = { items: [], total: 0 }
    if (request.url === '/customers') data = { items: [customer], total: 1 }
    else if (request.url === '/customers/options') data = {}
    else if (request.url === '/customer-requests') data = { items: [requestRow], total: 1 }
    else if (request.method === 'post') {
      const form = request.data
      const file = form instanceof FormData ? form.get('file') : null
      const bytes = file ? Array.from(new Uint8Array(await file.arrayBuffer())) : []
      state.posts.push({ url: request.url, amount: form?.get('amount'), request_id: form?.get('request_id'), data: form?.get('data'), file: file ? { name: file.name, type: file.type, bytes } : null })
      data = {}
    }
    return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
const mode = new URLSearchParams(location.search).get('mode') || 'customers'
const app = createApp({ setup() { const page = ref(null); onMounted(() => { state.page = page.value.$.setupState }); return () => h(mode === 'requests' ? Requests : Customers, { ref: page }) } })
app.use(createPinia())
app.use(createRouter({ history: createWebHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] }))
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
app.use(ElementPlus)
for (const [name, component] of Object.entries(Icons)) app.component(name, component)
for (const [name, component] of Object.entries({ GlassButton, StatusBadge, FilterBar, ListPageStatus, DetailDrawer })) app.component(name, component)
registerPermissionDirectives(app)
app.directive('sticky-scrollbar', {})
app.mount('#app')
