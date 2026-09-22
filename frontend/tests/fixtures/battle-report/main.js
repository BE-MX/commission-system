// Vite-only verification fixture; production router and login bootstrap are not mounted.
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '@/styles/tokens.css'
import '@/styles/liquid-glass.css'
import '@/styles/kimi-design.css'
import '@/styles/dashboard-theme.css'
import '@/styles/table-actions.css'
import '@/App.vue' // Platform-wide component styles; its bootstrap is not mounted.
import BattleReports from '@/views/battle-report/BattleReports.vue'
import { useAuthStore } from '@/stores/auth'
import { registerPermissionDirectives } from '@/directives/permission'

const app = createApp(BattleReports)
app.use(createPinia()).use(ElementPlus, { locale: zhCn })
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
const auth = useAuthStore()
auth.user = { id: 1, roles: ['super_admin'], permissions: [] }
registerPermissionDirectives(app)
app.mount('#app')
document.body.style.margin = '24px'
