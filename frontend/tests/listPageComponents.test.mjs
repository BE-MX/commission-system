import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'

const wrapper = { setup: (_, { slots, attrs }) => () => Vue.h('section', attrs, slots.default?.()) }
const button = { inheritAttrs: false, props: ['loading'], setup: (props, { slots, attrs }) => () => Vue.h('button', {
  ...attrs, disabled: props.loading, onClick: event => { if (!props.loading) attrs.onClick?.(event) },
}, slots.default?.()) }
function component(name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8'))
  const code = compileScript(descriptor, { id: name, inlineTemplate: true }).content
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, path) => {
      const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
      return `const ${declaration} = modules[${JSON.stringify(path)}];`
    }).replace('export default', 'return')
  return new Function('modules', code)({ vue: Vue, '@element-plus/icons-vue': {}, './GlassButton.vue': { default: button } })
}
function mount(t, component, props, slots) {
  const renderer = Vue.createRenderer({
    createElement: type => ({ type, children: [], props: {}, style: {} }), createText: text => ({ text }), createComment: () => ({}),
    insert(child, parent, anchor) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child); child.parent = parent
    },
    remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    patchProp(node, key, _, value) { node.props[key] = value }, setText(node, text) { node.text = text },
    setElementText(node, text) { node.text = text; node.children = [] }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const root = { children: [] }
  const app = renderer.createApp({ setup: () => () => Vue.h(component, props, slots) })
  app.component('el-alert', wrapper); app.mount(root)
  t.after(() => app.unmount())
  const text = node => [node.text || '', ...(node.children || []).map(text)].join('')
  const find = predicate => {
    const scan = node => [...(predicate(node) ? [node] : []), ...(node.children || []).flatMap(scan)]
    return scan(root)
  }
  return { app, text: () => text(root), find, buttons: label => find(node => node.type === 'button' && text(node).startsWith(label)) }
}

test('FilterBar submits once for text Enter, excludes IME/select/date and preserves collapsed fields', async t => {
  let searches = 0, resets = 0
  const props = Vue.reactive({ pending: true, loading: false, advancedCount: 1,
    onSearch: () => searches++, onReset: () => resets++ })
  const ui = mount(t, component('FilterBar'), props, {
    default: () => Vue.h('input'), advanced: () => Vue.h('input', { value: 'kept' }),
  })
  const bar = ui.find(node => node.props?.role === 'search')[0]
  const input = { tagName: 'INPUT', closest: () => null }
  const event = { key: 'Enter', target: input, preventDefault() { this.defaultPrevented = true } }
  bar.props.onKeydown(event)
  assert.equal(searches, 1)
  for (const extra of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { defaultPrevented: true },
    { target: { tagName: 'INPUT', closest: () => ({}) } }, { target: { tagName: 'BUTTON' } }]) {
    bar.props.onKeydown({ ...event, defaultPrevented: false, ...extra })
  }
  assert.equal(searches, 1)
  const advanced = ui.find(node => node.props?.class === 'filter-bar-advanced')[0]
  const field = ui.find(node => node.type === 'input' && node.props.value === 'kept')[0]
  assert.equal(advanced.style.display, 'none')
  ui.buttons('展开筛选')[0].props.onClick(); await Vue.nextTick()
  assert.equal(ui.buttons('收起筛选')[0].props['aria-expanded'], true)
  ui.buttons('收起筛选')[0].props.onClick(); await Vue.nextTick()
  assert.equal(ui.find(node => node.type === 'input' && node.props.value === 'kept')[0], field)
  assert.equal(field.props.value, 'kept')
  ui.buttons('查询')[0].props.onClick(); assert.equal(searches, 2)
  props.loading = true; await Vue.nextTick()
  bar.props.onKeydown({ ...event, defaultPrevented: false })
  ui.buttons('查询')[0].props.onClick(); assert.equal(searches, 2)
  ui.buttons('重置')[0].props.onClick(); assert.equal(resets, 1)
  assert.match(ui.text(), /查询后生效/)
})

test('ListPageStatus distinguishes error, retained page, loading and a successful empty result', async t => {
  let retries = 0
  const props = Vue.reactive({ error: 'offline', hasData: false, loading: false, dataPage: 3, onRetry: () => retries++ })
  const ui = mount(t, component('ListPageStatus'), props, { default: () => Vue.h('p', '暂无数据') })
  assert.doesNotMatch(ui.text(), /暂无数据/)
  ui.buttons('重试加载')[0].props.onClick(); assert.equal(retries, 1)
  props.hasData = true; await Vue.nextTick()
  assert.match(ui.text(), /第 3 页.*可能已过期/)
  props.error = ''; props.loading = true; await Vue.nextTick()
  assert.match(ui.text(), /正在加载/); assert.doesNotMatch(ui.text(), /暂无数据/)
  props.loading = false; await Vue.nextTick()
  assert.match(ui.text(), /暂无数据/)
})

test('unmount aborts the active request and rejects its late state changes', async t => {
  let state, context, reject
  const request = new Promise((_, fail) => { reject = fail })
  const ui = mount(t, { setup() {
    state = useListPage((_, supplied) => { context = supplied; return request })
    return () => Vue.h('div')
  } })
  ui.app.unmount()
  assert.equal(context.signal.aborted, true)
  assert.equal(context.isCurrent(), false)
  reject(new Error('late network failure')); await Vue.nextTick(); await Vue.nextTick()
  assert.equal(state.error.value, null)
  assert.equal(state.loading.value, false)
  assert.deepEqual(state.list.value, [])
})
