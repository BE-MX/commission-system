import { createApp, h } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/liquid-glass.css'
import DevlogBoard from '../../../src/views/devlog/DevlogBoard.vue'
import { registerStickyScrollbarDirective } from '../../../src/directives/stickyScrollbar'
import * as clients from '../../../src/api/clients'
// 每个请求都在浏览器内返回夹具数据；?state=stale|never|error|empty 切换状态
const state = new URLSearchParams(location.search).get('state') || 'fresh'
const item = (id, title, type, status, at, extra = {}) => ({ id, key: `branch:codex/${id}`, title, type, module: 'invoice', agent: 'codex',
  status, status_at: at, last_activity_at: at, stale: false, unmerged_hotfix: false, released_revision: null,
  preconditions: { migrations: [], config_keys: [], permissions: [] }, ...extra })
const items = state === 'empty' ? [] : [
  item(1, 'Add 9610 cross-border review', 'feature', 'pending_release', '2026-11-23T09:05',
    { preconditions: { migrations: ['276_invoice_alibaba_order', '277_cross_border_review'], config_keys: ['CROSS_BORDER_DXP_ID'], permissions: ['cross_border:read'] } }),
  item(2, 'Recover truncated strategies', 'bug', 'released', '2026-11-23T14:02', { released_revision: 'd1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d' }),
  item(3, 'Devlog board', 'feature', 'dev', '2026-11-23T15:10'),
  item(4, 'Private research evidence binding', 'bug', 'pending_merge', '2026-11-17T10:00', { stale: true }),
]
const col = s => s === 'dev' ? 'dev' : s === 'released' ? 'released' : 'committed'
const routes = {
  '/summary': (params = {}) => {
    const selected = items.filter(i => (!params.type || i.type === params.type) && (!params.module || i.module === params.module) && (!params.agent || i.agent === params.agent))
    const inPeriod = i => (!params.start || i.status_at.slice(0,10) >= params.start) && (!params.end || i.status_at.slice(0,10) <= params.end)
    const days = new Map()
    for (const i of selected.filter(inPeriod).sort((a,b) => b.status_at.localeCompare(a.status_at))) {
      const date = i.status_at.slice(0,10)
      if (!days.has(date)) days.set(date, [])
      days.get(date).push({ ...i, to_status: i.status, occurred_at: i.status_at })
    }
    const released = selected.filter(i => i.status === 'released' && (!params.start || i.status_at.slice(0,10) >= params.start) && (!params.end || i.status_at.slice(0,10) <= params.end))
    return { kpis: { features: released.filter(i => ['feature', 'improve'].includes(i.type)).length, bugs: released.filter(i => i.type === 'bug').length, data: 0, dev: selected.filter(i => i.status === 'dev').length, pending_release: selected.filter(i => i.status === 'pending_release').length, stale: selected.filter(i => i.stale).length },
    columns: { dev: selected.filter(i => col(i.status) === 'dev' && !i.stale), committed: selected.filter(i => col(i.status) === 'committed' && !i.stale), released },
    stale_columns: { dev: [], committed: selected.filter(i => i.stale), released: [] },
    timeline: [...days].map(([date, entries]) => ({ date, entries })) } },
  '/health': () => ({ ledger_pending_check: state === 'ledger-pending', last_sync_at: state === 'never' ? null : state === 'stale' ? '2026-11-23T07:12' : '2026-11-23T15:20',
    is_stale: ['stale', 'never'].includes(state), hours_since_sync: 8.1, sources: [{ name: 'git', ok: true }, { name: 'fetch', ok: true }, { name: 'releases', ok: true }],
    ledger_latest: { revision: 'd1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d', released_at: '2026-11-23T14:02:00', scope: 'office-and-cloud' } }),
  '/pending': () => ({ items: items.filter(i => i.status.startsWith('pending') && !i.stale).map(i => ({ ...i, ready: i.status === 'pending_release' && !i.preconditions.config_keys.length })) }),
}
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => {
  if (state === 'error' && config.url === '/health') return Promise.reject(Object.assign(new Error('fixture'), { config, response: { status: 500, data: {} } }))
  const detail = config.url.match(/^\/items\/(\d+)/)
  const data = detail ? { ...items.find(i => i.id === Number(detail[1])), evidences: [{ kind: 'commit', ref: 'b8c1bd75a1b2c3d4e5f60718293a4b5c6d7e8f90', at: '2026-11-23T09:05' }],
    events: [{ from_status: null, to_status: 'pending_merge', at: '2026-11-22T18:40' }] } : (routes[config.url]?.(config.params) ?? {})
  return { config, status: 200, headers: {}, data: { code: 200, message: 'ok', data } }
}
const app = createApp({ render: () => h('main', { style: 'padding:24px 28px' }, [h(DevlogBoard)]) }).use(ElementPlus)
registerStickyScrollbarDirective(app)
app.mount('#app')
