import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '@/styles/tokens.css'
import { knowledgeClient } from '@/api/clients'
import { useAuthStore } from '@/stores/auth'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import KnowledgeWorkbench from '@/views/knowledge/KnowledgeWorkbench.vue'
import KnowledgeDocumentPreview from '@/views/knowledge/components/KnowledgeDocumentPreview.vue'

const params = new URLSearchParams(location.search)
const viewer = params.has('viewer')
const storageKey = 'knowledge-authoring-fixture'
const requests = window.fixtureRequests = []
let saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null')

function persist(document) {
  saved = document
  sessionStorage.setItem(storageKey, JSON.stringify(document))
}

knowledgeClient.defaults.adapter = async config => {
  const { method, url, data } = config
  const payload = data ? JSON.parse(data) : null
  requests.push({ method, url, payload })
  let result
  if (method === 'get' && url === '/libraries') {
    result = [{ id: 1, name: '编辑器测试知识库', category: 'company', role: viewer ? 'viewer' : 'editor' }]
  } else if (method === 'get' && url === '/libraries/1/tree') {
    result = saved ? [{ id: saved.id, title: saved.title, node_type: 'document', status: 'draft', parent_id: null }] : []
  } else if (method === 'post' && url === '/libraries/1/documents' && !viewer) {
    persist({ id: 1, library_id: 1, node_type: 'document', title: payload.title, content_json: payload.content,
      status: 'draft', version_no: 1, revision_id: 1 })
    result = { id: 1, node_type: 'document' }
  } else if (method === 'get' && url === '/documents/1' && saved) {
    result = { ...saved, can_edit: !viewer }
  } else if (method === 'put' && url === '/documents/1' && saved && !viewer) {
    persist({ ...saved, title: payload.title, content_json: payload.content,
      version_no: saved.version_no + 1, revision_id: saved.revision_id + 1 })
    result = { id: saved.revision_id, version_no: saved.version_no }
  } else {
    throw new Error(`Unexpected fixture request: ${method} ${url}`)
  }
  return { config, data: { code: 200, data: result }, status: 200, statusText: 'OK', headers: {} }
}

const component = params.has('preview')
  ? { render: () => h(KnowledgeDocumentPreview, { content: saved.content_json }) }
  : KnowledgeWorkbench
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component }] })
const app = createApp({ render: () => h(RouterView) })
app.use(createPinia())
app.use(ElementPlus, { locale: zhCn })
app.use(router)
useAuthStore().user = { id: 1, permissions: viewer ? ['knowledge:read'] : ['knowledge:read', 'knowledge:write'] }
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
for (const item of [DetailDrawer, FilterBar, GlassButton, ListPageStatus, StatusBadge]) {
  app.component(item.name || item.__name, item)
}
await router.isReady()
app.mount('#app')
