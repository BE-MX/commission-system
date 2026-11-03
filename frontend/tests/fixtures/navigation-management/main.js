import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import NavigationManagement from '../../../src/views/system/navigation-management/NavigationManagement.vue'
import SidebarNavigation from '../../../src/views/layout/SidebarNavigation.vue'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import { useAuthStore } from '../../../src/stores/auth'
import * as clients from '../../../src/api/clients'
// No real backend transport is reachable from this fixture.
for (const [name, client] of Object.entries(clients)) {
  if (!client?.defaults) continue
  if (name === 'systemClient') client.defaults.baseURL = 'http://127.0.0.1:8891/api/system'
  else client.defaults.adapter = async config => ({ data: { code: 200, data: { phase: 'legacy_only' } }, status: 200, headers: {}, config })
}
const pinia = createPinia()
const auth = useAuthStore(pinia)
auth.user = { id: 7, real_name: '隔离验收', roles: ['super_admin'], permissions: [] }
const router = createRouter({history:createWebHashHistory(),routes:[{path:'/:pathMatch(.*)*',component:NavigationManagement}]})
const app = createApp({components:{SidebarNavigation},template:'<div style="display:flex;min-height:100dvh;background:var(--bg-page)"><SidebarNavigation class="fixture-sidebar" :collapsed="false"/><div class="fixture-content" style="flex:1;min-width:0;padding:24px"><router-view/></div></div>'})
app.use(pinia).use(router).use(ElementPlus)
registerPermissionDirectives(app)
registerStickyScrollbarDirective(app)
app.mount('#app')
