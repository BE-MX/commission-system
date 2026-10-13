import { createApp, ref } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import SidebarNavigation from '../../../src/views/layout/SidebarNavigation.vue'
import { NAV_ENTRIES } from '../../../src/config/navigation'
import { useAuthStore } from '../../../src/stores/auth'
import { authApi } from '../../../src/api/auth'
import * as clients from '../../../src/api/clients'

// This fixture never contacts the application backend; preferences use isolated SQLite.
for (const [key, client] of Object.entries(clients)) {
  if (!client?.defaults) continue
  if (key === 'systemClient') client.defaults.baseURL = 'http://127.0.0.1:8347/api/system'
  else client.defaults.adapter = async config => ({ data: { code: 200, data: {} }, status: 200, statusText: 'OK', headers: {}, config })
}
authApi.login = async ({ username }) => fetch(`http://127.0.0.1:8347/fixture/users/${username}`).then(result => result.json())
const router = createRouter({ history: createWebHashHistory(), routes: NAV_ENTRIES.filter(item => !item.external).map(item => ({
  path: item.path, name: item.name, meta: { title: item.title, activeMenu: item.activeMenu }, component: { template: '<h1>{{ $route.meta.title }}</h1>' },
})) })
const app = createApp({
  components: { SidebarNavigation },
  setup() {
    const auth = useAuthStore(), collapsed = ref(false)
    const initial = sessionStorage.getItem('nav-fixture-user') || 'alice'
    async function login(name) { sessionStorage.setItem('nav-fixture-user', name); await auth.login(name, 'fixture'); }
    function restrict() { auth.user = { ...auth.user, roles: [], permissions: [] } }
    login(initial)
    return { auth, collapsed, login, restrict }
  },
  template: `<div style="display:flex;height:100dvh"><SidebarNavigation :collapsed="collapsed"/><main style="padding:20px;flex:1;min-width:0">
    <button @click="login('alice')">Alice</button><button @click="login('bob')">Bob</button>
    <button @click="collapsed = !collapsed">折叠</button><button @click="restrict">撤销权限</button>
    <p data-user>{{auth.user?.username}}</p><router-view /></main></div>`,
})
app.use(createPinia()).use(router).use(ElementPlus)
app.directive('permission', { mounted(el) { el.style.display = 'none' } })
app.mount('#app')
