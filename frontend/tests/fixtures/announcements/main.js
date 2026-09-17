// Isolated UI fixture: all API calls use an in-memory adapter. No backend traffic.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/table-actions.css'
import GlassButton from '../../../src/components/GlassButton.vue'
import AnnouncementList from '../../../src/views/announcement/AnnouncementList.vue'
import { useAuthStore } from '../../../src/stores/auth'
import { announcementClient, knowledgeClient } from '../../../src/api/clients'
import { registerPermissionDirectives } from '../../../src/directives/permission'

const config = { initialized: true, library_id: 1, group_name: '企业公告测试群', conversation_id: 'fixture-only', robot_code: 'fixture-only', channel_verified: true, delivery_enabled: true, weekly_enabled: true, weekly_hour: 9, weekly_minute: 0, preset_name: 'weekly', executor_id: 1, version: 1 }
let categories = [{ id: 10, title: '公司通知', active: true }, { id: 11, title: '培训活动', active: true }]
let rows = [{ id: 1, title: '九月产品知识培训安排', category_id: 11, category_name: '培训活动', status: 'published', published_at: '2026-09-17T09:00:00', expires_at: '2026-09-25T18:00:00', important: true, pinned: true, version_no: 1, revision_id: 1,
  content_json: { type: 'doc', content: [{ type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: '培训安排' }] }, { type: 'paragraph', content: [{ type: 'text', text: '请销售同事于周五前完成培训报名。培训内容包括产品知识、客户沟通及售后流程。' }] }] },
  deliveries: [{ id: 1, source_key: 'publication:1', status: 'sent' }], library_id: 1 },
{ id: 2, title: '国庆放假安排（待审核）', category_id: 10, category_name: '公司通知', status: 'pending', pending_approval_id: 2, version_no: 1, revision_id: 2, library_id: 1,
  content_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '请各部门安排好节前工作交接。' }] }] }, deliveries: [] }]
const response = (request, data) => ({ data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request })
announcementClient.defaults.adapter = async request => {
  const path = request.url, data = request.data ? JSON.parse(request.data) : {}
  let result
  if (path === '/config') result = config
  else if (path === '/categories') result = categories
  else if (path === '/members' || path === '/member-candidates') result = [{ user_id: 1, username: 'fixture', real_name: '隔离测试账号', role: 'admin' }]
  else if (path === '/deliveries') result = [{ id: 1, source_key: 'publication:1', sequence: 1, status: 'sent' }]
  else if (path === '/weekly') result = [{ id: 1, generation: 1, period_start: '2026-09-07T00:00:00', status: 'ready', body: '上周公告回顾\n新增或更新 2 篇。\n\n培训活动：产品知识培训报名。' }]
  else if (path === '' && request.method === 'post') {
    const row = { ...data, id: rows.length + 1, library_id: 1, status: 'draft', revision_id: rows.length + 1, content_json: data.content, category_name: categories.find(c => c.id === data.category_id)?.title, deliveries: [] }
    rows.push(row); result = { id: row.id }
  } else if (path === '') {
    const matching = rows.filter(r => !request.params?.q || r.title.includes(request.params.q))
    result = { items: matching, total: matching.length }
  } else {
    const match = path.match(/^\/(\d+)(?:\/(\w+))?$/), row = rows.find(r => r.id === Number(match?.[1])), action = match?.[2]
    if (!row) throw new Error(`Fixture route not implemented: ${path}`)
    if (action === 'preview') result = [{ kind: 'text', text: row.title + '\n完整公告图文预览' }]
    else if (action === 'submit') { row.status = 'pending'; row.pending_approval_id = row.id; result = row }
    else if (action === 'review') { row.status = data.approve ? 'published' : 'draft'; row.pending_approval_id = null; result = row }
    else if (request.method === 'put') { Object.assign(row, data, { content_json: data.content ?? row.content_json, revision_id: row.revision_id + 1 }); result = { id: row.id } }
    else result = { ...row, can_review: true, can_edit: !!request.params?.edit && !row.pending_approval_id }
  }
  return response(request, result)
}
knowledgeClient.defaults.adapter = request => Promise.reject(new Error(`Fixture blocked knowledge request: ${request.url}`))
const pinia = createPinia()
const router = createRouter({ history: createWebHashHistory(), routes: [{ path: '/:pathMatch(.*)*', component: AnnouncementList }] })
const app = createApp({ render: () => h(RouterView) })
app.use(pinia)
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: [] }
app.use(router).use(ElementPlus)
app.component('GlassButton', GlassButton)
for (const [name, icon] of Object.entries(icons)) app.component(name, icon)
registerPermissionDirectives(app)
app.mount('#app')
