import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as Vue from 'vue'
import { createSSRApp, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import { transform } from 'esbuild'
import {
  availableViews, deltaInfo, groupInsights, heatLevel, nextView, percent, qualityDescription, shortDate, weekday,
} from '../src/views/domestic_followup/components/stats/statsModel.js'
import { useStatsBoard } from '../src/views/domestic_followup/composables/useStatsBoard.js'

async function loadStatsBoardComponent() {
  const url = new URL('../src/views/domestic_followup/components/stats/StatsBoard.vue', import.meta.url)
  const source = await readFile(url, 'utf8')
  const { descriptor } = parse(source, { filename: url.pathname })
  const script = compileScript(descriptor, { id: 'stats-board-test' })
  const { code } = await transform(script.content, { format: 'cjs', loader: 'js' })
  const emptyComponent = { render: () => null }
  const requireStub = id => {
    if (id === 'vue') return Vue
    if (id === '../../composables/useStatsBoard') return { useStatsBoard }
    if (id === './statsModel') return { availableViews, nextView }
    if (id === '@/api/domesticFollowup') return { apiError: (_error, fallback) => fallback }
    if (id === '@/utils/feedback') return { msgError: () => {}, msgSuccessText: () => {} }
    if (id === '@element-plus/icons-vue') return { MagicStick: emptyComponent, User: emptyComponent, UserFilled: emptyComponent }
    if (id.endsWith('.vue')) return { default: emptyComponent }
    throw new Error(`Unexpected StatsBoard import: ${id}`)
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(requireStub, module, module.exports)
  return module.exports.default
}

test('stats board setup starts the initial personal request without crashing', async () => {
  let calls = 0
  const api = {
    personalStats: async () => {
      calls += 1
      return { roster: [], people: [] }
    },
  }
  const StatsBoard = await loadStatsBoardComponent()
  const app = createSSRApp(StatsBoard, { api, canReadAll: true })
  app.config.errorHandler = error => { throw error }
  await renderToString(app)
  assert.equal(calls, 1)
})

test('sales gets two dock views and keyboard navigation wraps without team', () => {
  assert.deepEqual(availableViews(false).map(item => item.key), ['personal', 'ai'])
  assert.equal(nextView('personal', false, 1), 'ai')
  assert.equal(nextView('ai', false, 1), 'personal')
  assert.deepEqual(availableViews(true).map(item => item.key), ['personal', 'team', 'ai'])
})

test('metric formatting keeps nulls and uses percentage points for rates', () => {
  assert.equal(percent(null), '—')
  assert.equal(percent(0.625), '63%')
  assert.deepEqual(deltaInfo(0.62, 0.58, { percentagePoints: true }), { text: '+4 个百分点', direction: 'up' })
  assert.equal(deltaInfo(12, 8, { inverse: true }).direction, 'down')
  assert.equal(heatLevel(0), 0)
  assert.equal(heatLevel(7), 4)
  assert.equal(shortDate('2026-11-12'), '11/12')
  assert.equal(weekday('2026-11-12'), '周四')
  assert.match(qualityDescription('commitment'), /未顺延/)
})

test('insight groups never mix personal and company categories', () => {
  const items = [{ category: 'deal', id: 1 }, { category: 'common', id: 2 }]
  assert.deepEqual(groupInsights(items, 'deal').map(item => item.id), [1])
  assert.deepEqual(groupInsights(items, 'common').map(item => item.id), [2])
})

test('personal and AI person filters stay independent', async () => {
  const api = {
    personalStats: async () => ({ roster: [{ id: 7, real_name: '宋洋' }], people: [], team_average: null }),
    insights: async () => ({ refresh: { status: 'idle' } }),
  }
  const board = useStatsBoard(api, ref(true))
  await board.loadPersonal()
  board.person.value = 'all'
  await board.changeAiPerson(7)
  assert.equal(board.person.value, 'all')
  assert.equal(board.aiPerson.value, 7)
})

test('late personal response cannot replace the newest range', async () => {
  const pending = []
  const api = { personalStats: params => new Promise(resolve => pending.push({ params, resolve })) }
  const board = useStatsBoard(api, ref(false))
  const first = board.loadPersonal()
  board.range.value = 'w'
  const second = board.loadPersonal()
  pending[1].resolve({ period: { range: 'w' }, roster: [], people: [] })
  await second
  pending[0].resolve({ period: { range: '30' }, roster: [], people: [] })
  await first
  assert.equal(board.personal.data.period.range, 'w')
  assert.equal(board.personal.loading, false)
})

test('refresh tracks admitted job ids across person switches and waits for every job', async () => {
  const polled = []
  let rounds = 0
  const api = {
    refreshInsights: async () => ({ snapshot_ids: [21, 22] }),
    insightRefreshStatus: async id => { polled.push(id); if (id === 21) rounds += 1; return { id, status: rounds < 2 ? 'running' : 'done' } },
    insights: async () => ({ refresh: { status: 'done' } }),
  }
  const board = useStatsBoard(api, ref(true), { pollDelay: 0, pollAttempts: 3 })
  board.aiPerson.value = 7
  const refreshing = board.refreshInsights()
  board.aiPerson.value = 8
  assert.equal(await refreshing, true)
  assert.deepEqual(polled, [21, 22, 21, 22])
  assert.equal(board.refreshing.value, false)
})

test('failed and still-running refreshes never report success or erase previous suggestions', async () => {
  for (const status of ['failed', 'running']) {
    const snapshot = { personal: { id: 10, items: [{ id: 1 }] }, refresh: { status } }
    const api = { refreshInsights: async () => ({ snapshot_ids: [11] }),
      insightRefreshStatus: async () => ({ id: 11, status }), insights: async () => snapshot }
    const board = useStatsBoard(api, ref(false), { pollDelay: 0, pollAttempts: 1 })
    board.insights.data = snapshot
    assert.equal(await board.refreshInsights(), false)
    assert.equal(board.insights.data.personal.id, 10)
    assert.match(board.insights.error, status === 'failed' ? /失败/ : /后台/)
  }
})

test('generic server errors show an actionable Chinese fallback', async () => {
  const board = useStatsBoard({ personalStats: async () => { throw { response: { status: 500 }, message: 'Request failed with status code 500' } } }, ref(false))
  await board.loadPersonal()
  assert.equal(board.personal.error, '个人统计加载失败，请重新加载')
})
