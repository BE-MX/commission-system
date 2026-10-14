// Isolated real-component fixture. Adapters prevent every backend request.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import axios from 'axios'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import Editor from '../../../src/views/announcement/AnnouncementEditor.vue'
import KnowledgeEditor from '../../../src/views/knowledge/components/KnowledgeEditor.vue'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import DetailDrawer from '../../../src/components/DetailDrawer.vue'
import GlassButton from '../../../src/components/GlassButton.vue'
import { announcementClient, knowledgeClient } from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'

const params = new URLSearchParams(location.search)
const config = { library_id: 1, delivery_enabled: false, channel_verified: false }
const categories = [{ id: 10, title: '公司通知', active: true }]
const initial = { id: 1, library_id: 1, title: '图片编辑回归', category_id: 10, status: 'draft',
  revision_id: 20, can_edit: !params.has('viewer'), push_dingtalk: false,
  content_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '原有正文' }] }] } }
let document = JSON.parse(sessionStorage.getItem('image-test-document') || JSON.stringify(initial))
document.can_edit = initial.can_edit
const assets = new Map()
const state = window.imageTest = { uploads: [], saves: [], deletes: [], delay: 0, fail: false }
const response = (request, data) => ({ data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request })
const blocked = request => { throw new Error(`Blocked fixture request: ${request.method} ${request.url}`) }
announcementClient.defaults.adapter = async request => {
  if (request.url !== '/1') return blocked(request)
  if (request.method === 'get') return response(request, document)
  if (request.method !== 'put') return blocked(request)
  const payload = JSON.parse(request.data)
  state.saves.push(payload)
  document = { ...document, ...payload, content_json: payload.content, revision_id: document.revision_id + 1 }
  sessionStorage.setItem('image-test-document', JSON.stringify(document))
  return response(request, { id: 1 })
}
knowledgeClient.defaults.adapter = async request => {
  // Opt-in real XHR for transport tests; Playwright intercepts every API request.
  if (state.realTransport) return axios.getAdapter('xhr')(request)
  if (request.method === 'post' && request.url === '/libraries/1/assets') {
    const file = request.data.get('file')
    state.uploads.push({ name: file.name, type: file.type, size: file.size })
    const id = state.uploads.length
    if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay))
    if (state.fail) throw new Error('Fixture upload failure')
    assets.set(id, file)
    return response(request, { id, mime_type: file.type, width: 1, height: 1 })
  }
  const id = Number(request.url.match(/^\/assets\/(\d+)/)?.[1])
  if (request.method === 'get' && request.url.endsWith('/content')) {
    // Saved fixture images remain available across reloads, like persisted assets.
    const blob = assets.get(id) || new Blob([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGOUq1jFgA0wYRUdtBIA/fwBUFSn/xkAAAAASUVORK5CYII='), c => c.charCodeAt(0))], { type: 'image/png' })
    return { ...response(request, null), data: blob }
  }
  if (request.method === 'delete' && id) { state.deletes.push(id); assets.delete(id); return response(request, { id }) }
  return blocked(request)
}
const app = createApp({ render: () => h('main', { style: 'padding:24px;max-width:900px;margin:auto' }, [
  params.has('knowledge') ? h(KnowledgeEditor, { document, role: document.can_edit ? 'editor' : 'viewer' })
    : h(Editor, { config, categories, documentId: 1, edit: true }),
]) })
app.use(createPinia())
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: ['announcement:admin'] }
app.use(ElementPlus)
app.component('StatusBadge', StatusBadge)
app.component('DetailDrawer', DetailDrawer)
app.component('GlassButton', GlassButton)
registerPermissionDirectives(app)
app.mount('#app')
