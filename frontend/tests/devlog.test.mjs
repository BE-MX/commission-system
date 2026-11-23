import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { COLUMN_LABELS, STATUS_LABELS, TYPE_META, readinessLabel, rangeFor, preconditionTags } from '../src/views/devlog/devlogPresentation.js'

test('range presets are Beijing calendar based and inclusive', () => {
  assert.deepEqual(rangeFor('day', '2026-11-23'), { start: '2026-11-23', end: '2026-11-23' })
  assert.deepEqual(rangeFor('week', '2026-11-23'), { start: '2026-11-17', end: '2026-11-23' })
  assert.deepEqual(rangeFor('month', '2026-11-23'), { start: '2026-11-01', end: '2026-11-23' })
})

test('status, column and type labels cover every backend value', () => {
  for (const s of ['dev', 'pending_merge', 'pending_push', 'pending_release', 'released']) assert.ok(STATUS_LABELS[s])
  assert.deepEqual(Object.keys(COLUMN_LABELS), ['dev', 'committed', 'released'])
  for (const t of ['feature', 'improve', 'bug', 'data', 'ops', 'docs']) assert.ok(TYPE_META[t].label && TYPE_META[t].tone)
})

test('readiness wording tells what to do next', () => {
  assert.equal(readinessLabel({ status: 'pending_merge', ready: false }), '先合入 main')
  assert.equal(readinessLabel({ status: 'pending_push', ready: false }), '先推送')
  assert.equal(readinessLabel({ status: 'pending_release', ready: false }), '先完成前提')
  assert.equal(readinessLabel({ status: 'pending_release', ready: true }), '可以')
})

test('precondition tags list migrations, config and permissions', () => {
  assert.deepEqual(preconditionTags({ migrations: ['277_x'], config_keys: ['A_B'], permissions: ['x:read'] }).map(t => t.text),
    ['迁移 277_x', '配置 A_B', '权限 x:read'])
})

test('api module uses the shared client and no raw colors leak into the page', async () => {
  const api = await readFile(new URL('../src/api/devlog.js', import.meta.url), 'utf8')
  assert.match(api, /from '\.\/clients'/)
  const page = await readFile(new URL('../src/views/devlog/DevlogBoard.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(page.replace(/<!--[\s\S]*?-->/g, ''), /#[0-9a-fA-F]{3,8}\b/)
})
import * as Vue from 'vue'
import { viewController } from './helpers/viewController.mjs'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { rangeFor as rangePreset } from '../src/views/devlog/devlogPresentation.js'

function boardController(t, api) {
  const { vm } = viewController(t, '../../src/views/devlog/composables/useDevlogBoard.js', 'useDevlogBoard', {
    '@/composables/useAsyncResource.js': { useAsyncResource },
    '@/utils/datetime.js': { currentBeijingDate: () => '2026-11-23' },
    '@/api/devlog.js': { devlogApi: api },
    '../devlogPresentation.js': { rangeFor: rangePreset },
  })
  const scope = Vue.effectScope()
  const board = scope.run(() => vm.useDevlogBoard())
  t.after(() => scope.stop())
  return board
}

test('health distinguishes loading, failed, never synced, stale and recovered states', async t => {
  let health = () => Promise.reject(new Error('offline'))
  const board = boardController(t, { health: () => health() })
  assert.equal(board.syncState.value, 'loading')
  assert.equal(board.stale.value, false)
  await board.health.load()
  assert.equal(board.syncState.value, 'unknown')
  health = async () => ({ data: { last_sync_at: null, is_stale: true } })
  await board.health.load()
  assert.equal(board.syncState.value, 'never')
  health = async () => ({ data: { last_sync_at: '2026-11-23T10:00', is_stale: true } })
  await board.health.load()
  assert.equal(board.syncState.value, 'stale')
  health = async () => ({ data: { last_sync_at: '2026-11-23T17:00', is_stale: false } })
  await board.health.load()
  assert.equal(board.syncState.value, 'fresh')
})

test('filter requests and detail races preserve latest user selection', async t => {
  const requests = [], details = []
  const board = boardController(t, {
    summary: async params => { requests.push(params); return { data: { kpis: {}, columns: { dev: [], committed: [], released: [] }, timeline: [] } } },
    item: (id, { signal }) => new Promise(resolve => details.push({ id, signal, resolve })),
  })
  board.filters.module = 'invoice'
  board.filters.agent = 'codex'
  board.pickKpi('bugs')
  await Vue.nextTick()
  assert.deepEqual(requests.at(-1), { start: '2026-11-17', end: '2026-11-23', type: '', module: 'invoice', agent: 'codex' })
  board.openItem(1); board.openItem(2)
  assert.equal(details[0].signal.aborted, true)
  details[1].resolve({ data: { id: 2 } }); await new Promise(resolve => setImmediate(resolve))
  details[0].resolve({ data: { id: 1 } }); await new Promise(resolve => setImmediate(resolve))
  assert.equal(board.detail.data.value.id, 2)
  board.pending.data.value = ['pending_merge', 'pending_push', 'pending_release'].map(status => ({ status, module: 'invoice', agent: 'codex' }))
  assert.equal(board.pendingReleaseCount.value, 1)
  board.pickKpi('pending_release')
  assert.equal(board.tab.value, 'pending')
})


test('all KPI drilldowns match their status and type semantics, and stale rows remain separate', t => {
  const board = boardController(t, {})
  const released = type => ({ id: type, status: 'released', type })
  board.summary.data.value.columns = { dev: [{ status: 'dev', type: 'feature' }], committed: [{ status: 'pending_merge', type: 'bug' }], released: ['feature', 'improve', 'bug', 'docs'].map(released) }
  board.summary.data.value.stale_columns = { dev: [{ status: 'dev', type: 'bug', stale: true }], committed: [], released: [] }
  board.pickKpi('features')
  assert.deepEqual(board.visibleColumns.value.released.map(i => i.type), ['feature', 'improve'])
  assert.equal(board.visibleColumns.value.committed.length, 0)
  board.pickKpi('bugs')
  assert.deepEqual(board.visibleColumns.value.released.map(i => i.type), ['bug'])
  board.pickKpi('dev')
  assert.equal(board.visibleColumns.value.dev.length, 1)
  assert.equal(board.staleColumns.value.dev.length, 1)
  assert.equal(board.visibleColumns.value.released.length, 0)
  board.pickKpi('data')
  assert.equal(Object.values(board.visibleColumns.value).flat().length, 0)
  board.pickKpi('data')
  assert.equal(board.focus.value, '')
})

test('new ledger and refresh failures downgrade retained data until a successful refresh', async t => {
  let fail = false
  const board = boardController(t, { summary: async () => {
    if (fail) throw new Error('offline')
    return { data: { kpis: { data: 1 }, columns: { dev: [{ status: 'dev', type: 'data' }], committed: [], released: [{ status: 'released', type: 'data' }] }, timeline: [] } }
  } })
  board.health.data.value = { last_sync_at: '2026-11-23T17:00', is_stale: false, ledger_pending_check: true }
  board.health.hasLoaded.value = true
  assert.equal(board.stale.value, true)
  board.health.data.value.ledger_pending_check = false
  await board.summary.load()
  board.pickKpi('data')
  assert.equal(board.visibleColumns.value.dev.length, 0)
  assert.equal(board.visibleColumns.value.released.length, 1)
  fail = true
  await board.summary.load()
  assert.equal(board.summary.data.value.kpis.data, 1)
  assert.equal(board.summary.isStale.value, true)
  assert.equal(board.stale.value, true)
  fail = false
  await board.summary.load()
  assert.equal(board.stale.value, false)
})
