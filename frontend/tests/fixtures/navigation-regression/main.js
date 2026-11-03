import { createApp, ref } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import SidebarNavigation from '../../../src/views/layout/SidebarNavigation.vue'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import catalog from '../../../../backend/app/system/navigation_config_catalog.json'
import NavigationManagement from '../../../src/views/system/navigation-management/NavigationManagement.vue'
import * as clients from '../../../src/api/clients'
// All requests are handled locally; this fixture cannot write to any application service.
const draft = catalog.nodes.map(node => ({ ...node, icon: 'Document' }))
draft[0].label = '保留草稿名称'
draft[0].badge = 'NEW'
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => ({
  config, status: 200, headers: {}, data: { code: 200, data: config.url.includes('navigation-config/effective')
    ? { version: 0, nodes: catalog.nodes }
    : config.url.includes('navigation-config/catalog') ? { ...catalog, catalog_hash: 'a'.repeat(64) }
      : config.url.includes('navigation-config/draft') ? { nodes: draft, base_version: 0, draft_revision: 1, catalog_hash: 'a'.repeat(64) }
        : config.url.includes('navigation-config/versions') ? { items: [{ id: 0, version: 0, nodes: catalog.nodes }] }
          : config.url.includes('navigation-preferences') ? { items: [] } : { phase: 'legacy_only' } },
})
const pinia = createPinia()
useAuthStore(pinia).user = { id: 7, roles: ['super_admin'], permissions: [] }
const router = createRouter({ history: createWebHashHistory(), routes: [{ path: '/:pathMatch(.*)*', component: NavigationManagement }] })
const app = createApp({ components: { SidebarNavigation }, setup() { return { collapsed: ref(false) } },
  template: '<div style="display:flex;height:100dvh"><SidebarNavigation :collapsed="collapsed"/><main style="padding:24px"><h1>导航回归验收</h1><button @click="collapsed = !collapsed">展开 / 折叠侧栏</button><p>使用真实侧栏组件与修正后的目录，全部请求由隔离适配器处理。</p><router-view/></main></div>' })
app.use(pinia).use(router).use(ElementPlus)
registerPermissionDirectives(app)
app.mount('#app')
