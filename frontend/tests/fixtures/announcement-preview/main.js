// Real bell, inbox and renderer; all business requests stay in memory.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import AnnouncementBell from '../../../src/components/announcement/AnnouncementBell.vue'
import { announcementClient, knowledgeClient } from '../../../src/api/clients'
import { useAuthStore } from '../../../src/stores/auth'
import { registerPermissionDirectives } from '../../../src/directives/permission'

const state = window.previewTest = { reads: [], imageLoads: [], delay: 0 }
const rows = [1, 2].map(id => ({ id, revision_id: id, title: `图片公告 ${id}`, category_name: '公司通知',
  published_at: '2026-10-15T09:00:00', is_read: false,
  content_json: { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: '点击下方图片查看原图。' }] },
    { type: 'knowledgeImage', attrs: { assetId: id, alt: `公告图片 ${id}`, caption: '原图尺寸 1600 × 1000' } },
    { type: 'knowledgeImage', attrs: { assetId: 99, alt: '加载失败图片' } },
  ] },
}))
const counts = () => ({ total: rows.length, announcement_count: rows.length, unread_count: rows.filter(row => !row.is_read).length })
const response = (request, data) => ({ data: { code: 200, message: 'ok', data }, status: 200, statusText: 'OK', headers: {}, config: request })
announcementClient.defaults.adapter = async request => {
  const path = request.url
  if (path === '/inbox/summary') return response(request, counts())
  if (path === '/inbox') return response(request, { ...counts(), items: rows.map(row => ({ ...row })) })
  const match = path.match(/^\/inbox\/(\d+)(\/read)?$/)
  const row = rows.find(row => row.id === Number(match?.[1]))
  if (!row) throw new Error(`Unexpected fixture request: ${path}`)
  if (match[2]) { row.is_read = true; state.reads.push(row.id); return response(request, counts()) }
  return response(request, { ...row })
}
const canvas = document.createElement('canvas')
canvas.width = 1600; canvas.height = 1000
const ctx = canvas.getContext('2d')
ctx.fillStyle = 'steelblue'; ctx.fillRect(0, 0, 1600, 1000)
ctx.fillStyle = 'white'; ctx.font = '80px sans-serif'; ctx.fillText('Original image 1600 x 1000', 120, 500)
const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'))
knowledgeClient.defaults.adapter = async request => {
  state.imageLoads.push(request.url)
  if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay))
  if (/\/assets\/[12]\/content$/.test(request.url)) return { ...response(request, null), data: blob }
  throw new Error('Fixture image unavailable')
}
const app = createApp({ render: () => h('header', { style: 'display:flex;justify-content:flex-end;padding:16px' }, h(AnnouncementBell)) })
app.use(createPinia()).use(ElementPlus)
useAuthStore().user = { id: 1, roles: ['super_admin'], permissions: ['announcement:read'] }
registerPermissionDirectives(app)
app.mount('#app')
