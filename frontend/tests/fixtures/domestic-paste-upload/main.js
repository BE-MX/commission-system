import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import Create from '../../../src/views/domestic/DomesticOrderCreate.vue'
import Draft from '../../../src/views/domestic/components/DomesticDraftItemDialog.vue'
import Edit from '../../../src/views/domestic/components/DomesticOrderEditDialog.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import * as clients from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'

const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAALElEQVR4nGM8VGPCQA3ARBVTGEYNIgaMBjZhMBpGhMFoGBEGo2FEGAy+MAIAjYgBolwySa8AAAAASUVORK5CYII='
const options = { product_types: [{value:'cap',label:'头套'}], order_categories: [], order_types: [], order_channels: [], attr_dicts: {}, special_attr_dicts: {}, standard_values: {}, special_values: {}, order_routes: [] }
const item = { id: 11, line_code: 'TEST-1', product_name: '测试产品', status: 0, order_qty: 1, original_price: 100, unit_price: 100, labor_fee: 0, attrs: { product_type: 'cap' }, hairstyle: '', color: '', style_requirement: '', remark: '', hairstyle_images: [], color_images: [], style_images: [], remark_images: [] }
const order = { id: 1, domestic_no: 'TEST-1', order_kind: 'business', order_category: 'normal', order_type: 'normal', status: 0, created_by: 1, items: [item] }
const state = window.domesticTest = { uploads: [], requests: [], delay: 30, fail: false }
for (const client of Object.values(clients)) {
  if (!client?.defaults) continue
  client.defaults.adapter = async request => {
    state.requests.push(`${request.method} ${request.url}`)
    let data = { items: [], total: 0 }
    if (request.url === '/options') data = options
    else if (request.url === '/orders/1') data = order
    else if (request.url === '/images' && request.method === 'post') {
      const file = request.data.get('file')
      state.uploads.push({ name: file.name, type: file.type, size: file.size })
      await new Promise(resolve => setTimeout(resolve, state.delay))
      if (state.fail) throw Object.assign(new Error('模拟上传失败'), { config: request })
      data = { path: `${state.uploads.length}-${file.name}`, url: png }
    } else if (request.url.startsWith('/images/')) {
      const blob = await (await fetch(png)).blob()
      return { data: blob, status: 200, statusText: 'OK', headers: {}, config: request }
    }
    return { data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
const mode = new URLSearchParams(location.search).get('mode') || 'create'
const app = createApp({ render: () => mode === 'draft' ? h(Draft, { order, options }) : mode === 'edit' ? h(Edit, { modelValue: true, orderId: 1, initialItemId: 11 }) : h(Create) })
app.use(createPinia())
app.use(createRouter({ history: createWebHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] }))
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
app.use(ElementPlus)
app.component('StatusBadge', StatusBadge)
registerPermissionDirectives(app)
app.mount('#app')
