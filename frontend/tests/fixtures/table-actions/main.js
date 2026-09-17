import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/table-actions.css'
import GlassButton from '../../../src/components/GlassButton.vue'
import Fixture from './TableActions.vue'

const app = createApp(Fixture)
app.use(ElementPlus)
app.component('GlassButton', GlassButton)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
app.mount('#app')
