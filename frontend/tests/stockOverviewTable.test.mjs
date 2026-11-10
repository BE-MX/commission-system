import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { viewController } from './helpers/viewController.mjs'
import { mountComponent } from './helpers/mountComponent.mjs'
import { useTableView } from '../src/composables/useTableView.js'

const storageKey = 'stock-overview-table-view'
const defaultCoreColumns = [
  'model', 'sales-30d', 'effective-enable-count', 'free-stock',
  'production-in-transit', 'safety-stock', 'suggested-qty', 'stock-status', 'status',
]
const legacyDefaultColumns = [
  'model', 'type', 'size', 'color', 'weight', 'sales-30d', 'sales-90d', 'avg-daily-sales',
  'enable-count', 'free-stock', 'real-count', 'effective-enable-count', 'production-in-transit',
  'stock-status', 'safety-stock', 'suggested-qty', 'status', 'source',
]
const allColumns = [
  'model', 'type', 'size', 'color', 'weight', 'sales-30d', 'sales-90d', 'avg-daily-sales',
  'effective-enable-count', 'free-stock', 'enable-count', 'real-count', 'production-in-transit',
  'safety-stock', 'suggested-qty', 'stock-status', 'status', 'source',
]

function definitions(t) {
  return viewController(t, '../../src/views/stock/composables/useStockOverviewTable.js', 'columnDefs').vm.columnDefs
}

function preferences(t, saved) {
  const storage = new Map(saved === undefined ? [] : [[storageKey, JSON.stringify(saved)]])
  const originalDocument = globalThis.document
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  globalThis.document = { body: { style: {} }, addEventListener() {}, removeEventListener() {} }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
  })
  t.after(() => {
    globalThis.document = originalDocument
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage)
    else delete globalThis.localStorage
  })
  return {
    storage,
    read: () => JSON.parse(storage.get(storageKey)),
    mount() {
      let table
      const host = { setup() {
        table = viewController(t, '../../src/views/stock/composables/useStockOverviewTable.js', 'table: useStockOverviewTable()', {
          '@/composables/useTableView': { useTableView },
        }).vm.table
        return () => Vue.h('div')
      } }
      const mounted = mountComponent(t, host)
      return { table, ...mounted }
    },
  }
}

function templateColumnKeys() {
  const source = readFileSync(new URL('../src/views/stock/StockOverview.vue', import.meta.url), 'utf8')
  return [...source.matchAll(/<el-table-column v-if="visibleKeys\.includes\('([^']+)'\)"/g)].map(match => match[1])
}

test('stock overview default desktop columns prioritize replenishment decisions in template order', t => {
  const columns = definitions(t)
  assert.deepEqual(columns.filter(column => column.defaultVisible !== false).map(column => column.key), defaultCoreColumns)
  assert.deepEqual(columns.map(column => column.key), allColumns)
  const templateKeys = templateColumnKeys()
  assert.deepEqual(templateKeys, allColumns)
  assert.deepEqual(templateKeys.filter(key => defaultCoreColumns.includes(key)), defaultCoreColumns)
})

test('stock overview migrates the old default all-column snapshot through useTableView and stays stable on reload', t => {
  const state = preferences(t, {
    version: 1, knownColumnKeys: legacyDefaultColumns, visibleKeys: legacyDefaultColumns,
    density: 'compact', futureMetadata: { retained: true },
  })
  const first = state.mount()
  assert.deepEqual(first.table.columnDefs.map(column => column.key), allColumns)
  assert.deepEqual(first.table.visibleKeys.value, defaultCoreColumns)
  assert.equal(first.table.density.value, 'compact')
  const persisted = state.read()
  assert.deepEqual(persisted.visibleKeys, defaultCoreColumns)
  assert.deepEqual(persisted.knownColumnKeys, allColumns)
  assert.equal(persisted.density, 'compact')
  assert.deepEqual(persisted.futureMetadata, { retained: true })
  first.app.unmount()
  const reloaded = state.mount()
  assert.deepEqual(reloaded.table.visibleKeys.value, defaultCoreColumns)
  assert.equal(reloaded.table.density.value, 'compact')
  assert.deepEqual(state.read(), persisted)
  reloaded.app.unmount()
})

test('stock overview recognizes a reordered legacy default snapshot with legacy metadata', t => {
  const state = preferences(t, {
    visibleKeys: [...legacyDefaultColumns].reverse(), density: 'comfort', legacyMetadata: 'retained',
  })
  const mounted = state.mount()
  assert.deepEqual(mounted.table.visibleKeys.value, defaultCoreColumns)
  assert.equal(mounted.table.density.value, 'comfort')
  assert.deepEqual(state.read().visibleKeys, defaultCoreColumns)
  assert.equal(state.read().legacyMetadata, 'retained')
  mounted.app.unmount()
})

test('stock overview preserves explicit column subsets and density without migration', t => {
  const state = preferences(t)
  for (const visibleKeys of [['source', 'type', 'model'], legacyDefaultColumns.slice(1)]) {
    state.storage.set(storageKey, JSON.stringify({
      version: 1, knownColumnKeys: legacyDefaultColumns, visibleKeys, density: 'compact',
    }))
    const mounted = state.mount()
    assert.deepEqual(mounted.table.visibleKeys.value, visibleKeys)
    assert.equal(mounted.table.density.value, 'compact')
    assert.deepEqual(state.read().visibleKeys, visibleKeys)
    mounted.app.unmount()
  }
})

test('stock overview stacks readable stat cards on narrow screens without changing desktop grid', () => {
  const styles = readFileSync(new URL('../src/views/stock/stock-overview.css', import.meta.url), 'utf8')
  const mobile = styles.match(/@media \(max-width: 640px\)\s*\{([\s\S]*)\}\s*$/)?.[1] || ''
  assert.match(styles, /\.stats-row \{ display: grid; grid-template-columns: repeat\(3, 1fr\); gap: 20px; \}/)
  assert.match(mobile, /\.stats-row\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/)
  assert.match(mobile, /\.stat-card\s*\{[^}]*padding:\s*16px;[^}]*gap:\s*12px;/)
  assert.match(mobile, /\.stat-info\s*\{[^}]*min-width:\s*0;/)
  assert.match(mobile, /\.stat-card \.status-badge\s*\{[^}]*flex-shrink:\s*0;/)
})


test('stock overview gives sortable core headers enough width and keeps derived daily sales optional', t => {
  const columns = definitions(t)
  assert.equal(columns.find(column => column.key === 'avg-daily-sales').defaultVisible, false)
  const source = readFileSync(new URL('../src/views/stock/StockOverview.vue', import.meta.url), 'utf8')
  const minimums = { '30天销量': 112, '可用库存': 112, '生产在途': 108, '安全库存': 110, '建议备货量': 120, '备货状态': 110 }
  for (const [label, minimum] of Object.entries(minimums)) {
    const column = source.match(new RegExp(`<el-table-column[^>]*label="${label}"[^>]*>`))?.[0] || ''
    const width = Number(column.match(/min-width="(\d+)"/)?.[1])
    assert.ok(width >= minimum, `${label} header width ${width} must be at least ${minimum}`)
  }
})


test('stock status filters use native pressed buttons with visible selection and focus', () => {
  const source = readFileSync(new URL('../src/views/stock/StockOverview.vue', import.meta.url), 'utf8')
  const styles = readFileSync(new URL('../src/views/stock/stock-overview.css', import.meta.url), 'utf8')
  const cards = source.match(/<button type="button" class="stat-card lg-card/g) || []
  assert.equal(cards.length, 3)
  for (const status of ['shortage', 'warning', 'sufficient']) {
    assert.match(source, new RegExp(`:class="\\{ 'is-active': filters\\.status\\.includes\\('${status}'\\) \\}"`))
    assert.match(source, new RegExp(`:aria-pressed="filters\\.status\\.includes\\('${status}'\\)"`))
  }
  assert.match(styles, /\.stat-card\.is-active\s*\{[^}]*border-color:\s*var\(--stat-accent\)/)
  assert.match(styles, /\.stat-card:focus-visible\s*\{[^}]*outline:/)
  assert.match(source, /class="stat-active-mark"/)
})


test('stock detail dialog keeps delivery visible and progress dialog names its business context', () => {
  const source = readFileSync(new URL('../src/views/stock/StockOverview.vue', import.meta.url), 'utf8')
  const detailTable = source.match(/<el-table v-if="\(currentStockStatusRow\.stock_items[\s\S]*?<\/el-table>/)?.[0] || ''
  const widths = [...detailTable.matchAll(/min-width="(\d+)"/g)].map(match => Number(match[1]))
  assert.equal(widths.length, 8)
  assert.ok(widths.reduce((sum, width) => sum + width, 0) <= 720, 'detail columns must fit the 760px dialog content')
  assert.match(detailTable, /prop="expected_delivery_date"[^>]*min-width="120"/)
  assert.match(source, /<button[^>]*type="button"[^>]*:class="\['stock-status-label'/)
  assert.match(source, /class="progress-context"[\s\S]*currentStockStatusRow\?\.product_name[\s\S]*progressDialogRow\.order_no[\s\S]*progressDialogRow\.batch_no/)
})
