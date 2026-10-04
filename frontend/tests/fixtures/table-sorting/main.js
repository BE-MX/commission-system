import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/liquid-glass.css'
import '../../../src/styles/app.css'
import '../../../src/styles/table-actions.css'
import { registerSortableTables } from '../../../src/components/SortableTableColumn'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import { useAuthStore } from '../../../src/stores/auth'
import GlassButton from '../../../src/components/GlassButton.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import FilterBar from '../../../src/components/FilterBar.vue'
import ListPageStatus from '../../../src/components/ListPageStatus.vue'
import DetailDrawer from '../../../src/components/DetailDrawer.vue'
import SupervisorRelation from '../../../src/views/supervisor/SupervisorRelation.vue'
import CustomerSnapshot from '../../../src/views/customer/CustomerSnapshot.vue'
import LocalTable from './LocalTable.vue'
import TreeTable from './TreeTable.vue'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/supervisor', component: SupervisorRelation }, { path: '/customer', component: CustomerSnapshot },
  { path: '/local', component: LocalTable },
  { path: '/tree', component: TreeTable },
] })
const app = createApp({ render: () => h('main', { style: 'padding:24px;--navigation-chrome-height:99px' }, [h(RouterView)]) })
app.use(createPinia()).use(router).use(ElementPlus, { locale: zhCn })
registerSortableTables(app)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
for (const [name, component] of Object.entries({ GlassButton, StatusBadge, FilterBar, ListPageStatus, DetailDrawer })) app.component(name, component)
const auth = useAuthStore()
auth.accessToken = 'isolated-qa-token'
auth.user = { id: 7, permissions: ['supervisor:read', 'supervisor:write', 'customer:read', 'customer:write'], roles: [] }
await router.push(new URLSearchParams(location.search).get('route') || '/local')
app.mount('#app')
