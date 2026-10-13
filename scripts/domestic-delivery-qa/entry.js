import { createApp, ref, h } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../src/styles/tokens.css'
import '../../src/styles/app.css'
import '../../src/styles/table-actions.css'
import '../../src/styles/liquid-glass.css'
import '../../src/styles/dashboard-theme.css'
import DomesticDeliveryDialog from '../../src/views/domestic/components/DomesticDeliveryDialog.vue'
import GlassButton from '../../src/components/GlassButton.vue'
import ListPageStatus from '../../src/components/ListPageStatus.vue'
import { useAuthStore } from '../../src/stores/auth'
import { registerPermissionDirectives } from '../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../src/directives/stickyScrollbar'
import { registerSortableTables } from '../../src/components/SortableTableColumn'
const app = createApp({ setup() {
  const dialog = ref(null)
  return () => h('div', [h('p', '隔离验收 · 虚构订单和客户 · 无生产连接'),
    h('button', { onClick: () => dialog.value.open() }, '从订单页打开'),
    h('button', { onClick: () => dialog.value.open({ id: 1, shop_name: '验收客户', settle_mode: 'credit' }) }, '从客户页打开'),
    h(DomesticDeliveryDialog, { ref: dialog })])
} })
app.use(createPinia()); app.use(ElementPlus, { locale: zhCn })
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
for (const [name, component] of Object.entries(icons)) app.component(name, component)
app.component('GlassButton', GlassButton); app.component('ListPageStatus', ListPageStatus)
registerPermissionDirectives(app); registerStickyScrollbarDirective(app); registerSortableTables(app)
app.mount('#app')
