import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/table-actions.css'
import GlassButton from '../../../src/components/GlassButton.vue'
import Showcase from '../../../src/views/system/ComponentShowcase.vue'

const app = createApp(Showcase)
app.use(ElementPlus)
app.component('GlassButton', GlassButton)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
app.mount('#app')
