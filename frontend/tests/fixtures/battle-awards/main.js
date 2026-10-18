// Isolated QA entry, never imported by the production router.
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '@/styles/tokens.css'
import '@/styles/liquid-glass.css'
import '@/App.vue'
import BattleReports from '@/views/battle-report/BattleReports.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth'
import { registerPermissionDirectives } from '@/directives/permission'

const app = createApp(BattleReports)
app.use(createPinia()).use(ElementPlus, { locale: zhCn })
app.component('StatusBadge', StatusBadge)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
registerPermissionDirectives(app)
app.mount('#app')
document.body.style.margin = '24px'
