import { createApp, ref, computed } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/views/system/navigation-management/navigation-management.css'
import SidebarNavigation from '../../../src/views/layout/SidebarNavigation.vue'
import NavigationPreviewBranch from '../../../src/views/system/navigation-management/NavigationPreviewBranch.vue'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'
import catalog from '../../../../backend/app/system/navigation_config_catalog.json'
import * as clients from '../../../src/api/clients'
// Every request is isolated; no application API or persistent database is reached.
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => ({
  config, status: 200, headers: {}, data: { code: 200, data: config.url.includes('navigation-config/effective')
    ? { version: 0, nodes: catalog.nodes } : config.url.includes('navigation-preferences') ? { items: [] } : { phase: 'legacy_only' } },
})
const pinia = createPinia()
useAuthStore(pinia).user = { id: 7, roles: ['super_admin'], permissions: [] }
const router = createRouter({ history: createWebHashHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<span />' } }] })
const app = createApp({ components: { SidebarNavigation, NavigationPreviewBranch }, setup() {
  const tone = ref('gold'), place = ref('icon'), compact = ref(false)
  const items = computed(() => [{ id: 'colorwork', title: '库存色块图', icon: 'Brush', badge: 'BY 加程', badgePlace: place.value, badgeTone: tone.value }])
  return { tone, place, compact, items }
}, template: `<div style="display:flex;height:100dvh"><SidebarNavigation :collapsed="compact"/><main style="padding:32px;min-width:0;flex:1"><h1>导航玻璃标签验收</h1><p>左侧为真实侧栏，右侧复用真实管理页预览组件。所有请求均已隔离。</p><label>标签色调 <select v-model="tone"><option value="gold">品牌金</option><option value="blue">信息蓝</option><option value="neutral">中性灰</option></select></label><label>位置 <select v-model="place"><option value="icon">图标角标</option><option value="text">名称右侧</option></select></label><button @click="compact = !compact">折叠侧栏</button><section class="navigation-preview-sidebar" style="width:300px;margin:32px 0;padding:36px 24px"><NavigationPreviewBranch :items="items"/></section><router-view/></main></div>` })
app.use(pinia).use(router).use(ElementPlus)
registerPermissionDirectives(app)
app.mount('#app')
