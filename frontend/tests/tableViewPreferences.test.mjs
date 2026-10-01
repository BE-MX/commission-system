import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { useTableView } from '../src/composables/useTableView.js'
import * as preferences from '../src/utils/tableViewPreferences.js'

const columns = [{ key: 'name', label: '名称' }, { key: 'status', label: '状态' }]
const tableToolsSource = readFileSync(new URL('../src/components/TableTools.vue', import.meta.url), 'utf8')
const { descriptor } = parse(tableToolsSource)
const compiled = compileScript(descriptor, { id: 'table-preferences', inlineTemplate: true }).content
  .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, path) => {
    const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
    return `const ${declaration} = modules[${JSON.stringify(path)}];`
  }).replace('export default', 'return')
const TableTools = new Function('modules', compiled)({
  vue: Vue, '@element-plus/icons-vue': {}, '../utils/tableViewPreferences.js': preferences,
})
const mountedApps = new WeakMap()

function environment(t, initial = {}) {
  mountedApps.set(t, [])
  const storage = new Map(Object.entries(initial))
  const originalDocument = globalThis.document
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  globalThis.document = { body: { style: {} }, addEventListener() {}, removeEventListener() {} }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
  })
  t.after(() => {
    mountedApps.get(t).forEach(app => app.unmount())
    globalThis.document = originalDocument
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage)
    else delete globalThis.localStorage
  })
  return storage
}

function mount(t, definitions = columns, activeColumns = definitions, pageKey = 'preferences') {
  let view
  const renderer = Vue.createRenderer({
    createElement: type => ({ type, children: [], props: {} }), createText: text => ({ text }), createComment: () => ({}),
    insert(child, parent, anchor) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
      child.parent = parent
    },
    remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    patchProp(node, key, _, value) { node.props[key] = value }, setText(node, text) { node.text = text },
    setElementText(node, text) { node.text = text; node.children = [] }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const wrapper = { setup: (_, { slots, attrs }) => () => Vue.h('section', attrs, slots.default?.()) }
  const app = renderer.createApp({ setup() {
    view = useTableView(pageKey, definitions)
    return () => Vue.h(TableTools, {
      columns: Vue.toValue(activeColumns), visibleKeys: view.visibleKeys.value, density: view.density.value,
      'onUpdate:visibleKeys': value => { view.visibleKeys.value = value },
      'onUpdate:density': value => { view.density.value = value },
    })
  } })
  for (const name of ['el-popover', 'el-tooltip', 'el-radio-group', 'el-radio', 'el-checkbox']) app.component(name, wrapper)
  app.component('GlassButton', { setup: (_, { slots, attrs }) => () => Vue.h('button', attrs, slots.default?.()) })
  const root = { children: [] }
  app.mount(root)
  mountedApps.get(t).push(app)
  function find(predicate, node = root) {
    return [...(predicate(node) ? [node] : []), ...(node.children || []).flatMap(child => find(predicate, child))]
  }
  return { app, view, find, reset: () => find(node => node.props?.['aria-label'] === '恢复默认列与密度')[0].props.onClick() }
}

test('legacy migration preserves hidden columns and upgrades known keys on first load', t => {
  const storage = environment(t, { 'preferences-table-view': JSON.stringify({ density: 'compact', visibleKeys: ['status', 'status', 'removed'] }) })
  const table = mount(t)
  assert.deepEqual(table.view.visibleKeys.value, ['status'])
  assert.equal(table.view.density.value, 'compact')
  assert.deepEqual(JSON.parse(storage.get('preferences-table-view')), {
    version: 1, knownColumnKeys: ['name', 'status'], density: 'compact', visibleKeys: ['status'],
  })
})

test('new columns follow defaults while old hidden columns remain hidden after reload', t => {
  const storage = environment(t, { 'preferences-table-view': JSON.stringify({
    version: 1, density: 'comfort', visibleKeys: ['status', 'status', 'obsolete'], knownColumnKeys: ['name', 'status', 'obsolete'],
  }) })
  const definitions = [...columns, { key: 'new' }, { key: 'optional', defaultVisible: false }, { key: 'new' }]
  const table = mount(t, definitions)
  assert.deepEqual(table.view.visibleKeys.value, ['status', 'new'])
  assert.deepEqual(table.view.visibleColumns.value.map(column => column.key), ['status', 'new'])
  assert.deepEqual(JSON.parse(storage.get('preferences-table-view')).knownColumnKeys, ['name', 'status', 'new', 'optional'])
  table.app.unmount()
  const reloaded = mount(t, definitions)
  assert.deepEqual(reloaded.view.visibleKeys.value, ['status', 'new'])
  assert.equal(reloaded.view.density.value, 'comfort')
})

test('damaged, unsupported and all-hidden preferences recover a usable view', t => {
  environment(t)
  const definitions = [{ key: 'name', defaultVisible: false }, { key: 'status', defaultVisible: false }]
  for (const saved of ['broken JSON', '{}', '[]', JSON.stringify({ version: 99, visibleKeys: ['status'] }),
    JSON.stringify({ version: 1, visibleKeys: ['status'] }),
    JSON.stringify({ version: 1, knownColumnKeys: ['name', 'status'], visibleKeys: [], density: 'bad' }),
    JSON.stringify({ visibleKeys: [null, 'removed', 'removed'] })]) {
    localStorage.setItem('preferences-table-view', saved)
    const table = mount(t, definitions)
    assert.deepEqual(table.view.visibleKeys.value, ['name'])
    assert.equal(table.view.density.value, 'default')
    table.app.unmount()
  }
})

test('empty columns and blocked storage keep view state usable in memory', t => {
  environment(t)
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('storage blocked') } })
  const table = mount(t)
  table.view.visibleKeys.value = null
  assert.deepEqual(table.view.visibleKeys.value, ['name', 'status'])
  table.view.visibleKeys.value = []
  assert.deepEqual(table.view.visibleKeys.value, ['name', 'status'])
  table.view.visibleKeys.value = ['status', 'status', 'unknown']
  assert.deepEqual(table.view.visibleKeys.value, ['status'])
  table.view.density.value = 'comfort'
  assert.equal(table.view.densityClass.value, 'density-comfort')
  table.view.density.value = 'invalid'
  assert.equal(table.view.density.value, 'default')
  const empty = mount(t, [], [], 'empty')
  assert.deepEqual(empty.view.visibleKeys.value, [])
  assert.equal(empty.find(node => node.props?.['aria-label'] === '恢复默认列与密度').length, 0)
})

test('restore button uses existing v-models and persists default columns and density', async t => {
  const storage = environment(t)
  const definitions = [...columns, { key: 'optional', defaultVisible: false }]
  const table = mount(t, definitions)
  table.view.visibleKeys.value = ['status', 'optional']
  table.view.density.value = 'compact'
  await Vue.nextTick()
  table.reset()
  assert.deepEqual(table.view.visibleKeys.value, ['name', 'status'])
  assert.equal(table.view.density.value, 'default')
  assert.deepEqual(JSON.parse(storage.get('preferences-table-view')).visibleKeys, ['name', 'status'])
  table.app.unmount()
  const reloaded = mount(t, definitions)
  assert.deepEqual(reloaded.view.visibleKeys.value, ['name', 'status'])
  assert.equal(reloaded.view.density.value, 'default')
})

test('tab subsets repair empty selection, prevent hiding last column and preserve other tabs on reset', async t => {
  environment(t)
  const materials = [{ key: 'material' }, { key: 'quantity' }]
  const mappings = [{ key: 'product' }, { key: 'note', defaultVisible: false }]
  const active = Vue.ref(materials)
  const table = mount(t, [...materials, ...mappings], active)
  table.view.visibleKeys.value = ['material']
  await Vue.nextTick()
  const checkbox = table.find(node => node.props?.['model-value'] === true && node.props.onChange)[0]
  assert.equal(checkbox.props.disabled, true)
  checkbox.props.onChange(false)
  assert.deepEqual(table.view.visibleKeys.value, ['material'])
  active.value = mappings
  await Vue.nextTick()
  assert.deepEqual(table.view.visibleKeys.value, ['material', 'product'])
  table.view.visibleKeys.value = ['material', 'note']
  await Vue.nextTick()
  table.reset()
  assert.deepEqual(table.view.visibleKeys.value, ['material', 'product'])
  active.value = materials
  await Vue.nextTick()
  table.reset()
  assert.deepEqual(table.view.visibleKeys.value, ['product', 'material', 'quantity'])
})

test('reactive column definitions add default-visible keys and remove obsolete keys', t => {
  environment(t)
  const definitions = Vue.ref(columns)
  const table = mount(t, definitions)
  table.view.visibleKeys.value = ['status']
  definitions.value = [{ key: 'name' }, { key: 'new' }, { key: 'optional', defaultVisible: false }]
  assert.deepEqual(table.view.visibleKeys.value, ['new'])
})
