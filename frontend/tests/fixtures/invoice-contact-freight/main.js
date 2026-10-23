// Render the real invoice page. Every business request uses an in-memory adapter.
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
import { emptyInvoiceForm } from '../../../src/views/invoice/composables/invoiceEditorState'

const state = window.invoiceTest = { saved: [], editor: null }
const contact = { contact_name: 'Alice', contact_phone: '123456', contact_email: 'alice@example.test', delivery_address: 'Test address', customer_grade: 'A' }
const customers = ['complete', 'incomplete'].map(id => ({ kind: 'customer', company_id: id, company_name: id, option_key: `customer:${id}` }))
let stored = { ...emptyInvoiceForm(), ...contact, id: 7, customer_id: 'complete', customer_name: 'complete', shipping_fee: 18.5, express_channel: 'FEDEX' }
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    let data = { items: [], total: 0, has_more: false }
    const url = request.url
    if (url === '/delegations/assignees') data.items = [{ id: 1, real_name: 'Test sales', username: 'test', okki_bound: true, okki_department_configured: true }]
    else if (url === '/customers/options') data = { items: customers, total: 2, has_more: false, okki_bound: true }
    else if (url === '/customers/contact-defaults') data = { ...contact, contact_phone: request.params.customer_id === 'incomplete' ? '' : contact.contact_phone }
    else if (url.includes('/price/customer-rules/') || url.endsWith('/linked-sync')) data = null
    else if (url === '/invoices/suggest-no') data = { invoice_no: 'TEST-NEW' }
    else if (url === '/invoices/check-no') data = { exists: false }
    else if (url === '/shipments/capabilities') data = { enabled: true }
    else if (url === '/invoices/summary') data = { gmv: 0, average_order_amount: 0 }
    else if (url.endsWith('/validate') || url.endsWith('/sync')) data = { ok: true }
    else if (request.method === 'post' || request.method === 'put') {
      const payload = typeof request.data === 'string' ? JSON.parse(request.data) : request.data
      state.saved.push(payload)
      stored = { ...payload, id: 7 }
      data = stored
    } else if (url === '/invoices/7') data = stored
    return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
const pinia = createPinia()
const app = createApp({
  setup() {
    const page = ref(null)
    onMounted(() => { state.editor = page.value.$.setupState.editor })
    return () => h(InvoiceManage, { ref: page })
  },
})
app.use(pinia)
const auth = useAuthStore()
auth.user = { id: 1, roles: ['super_admin'], permissions: [] }
auth.accessToken = 'isolated-fixture'
app.use(ElementPlus)
app.component('GlassButton', GlassButton)
app.component('FilterBar', FilterBar)
app.component('ListPageStatus', ListPageStatus)
app.component('StatusBadge', StatusBadge)
registerPermissionDirectives(app)
app.directive('sticky-scrollbar', {})
app.mount('#app')
