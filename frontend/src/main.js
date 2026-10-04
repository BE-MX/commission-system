import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './styles/tokens.css'
import './styles/liquid-glass.css'
import './styles/kimi-design.css'
import './styles/dashboard-theme.css'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/table-actions.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import GlassButton from './components/GlassButton.vue'
import StatusBadge from './components/StatusBadge.vue'
import ResponsiveDescriptions from './components/ResponsiveDescriptions.vue'
import EmptyState from './components/EmptyState.vue'
import FilterBar from './components/FilterBar.vue'
import ListPageStatus from './components/ListPageStatus.vue'
import DetailDrawer from './components/DetailDrawer.vue'
import { registerPermissionDirectives } from './directives/permission'
import { registerStickyScrollbarDirective } from './directives/stickyScrollbar'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.component('GlassButton', GlassButton)
app.component('StatusBadge', StatusBadge)
app.component('ResponsiveDescriptions', ResponsiveDescriptions)
app.component('EmptyState', EmptyState)
app.component('FilterBar', FilterBar)
app.component('ListPageStatus', ListPageStatus)
app.component('DetailDrawer', DetailDrawer)
registerPermissionDirectives(app)   // v-permission / v-any-permission（按钮级权限）
registerStickyScrollbarDirective(app) // v-sticky-scrollbar（宽表悬浮横向滚动条，DESIGN.md 宽表规范）

app.use(createPinia())
app.use(ElementPlus, { locale: zhCn })
app.use(router)
app.mount('#app')
