import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import * as editing from '../src/views/domestic/domesticOrderEditing.js'
import * as attributes from '../src/views/domestic/domesticAttributeRules.js'
import * as kinds from '../src/views/domestic/domesticOrderKinds.js'
import * as latest from '../src/views/domestic/composables/latestRequest.js'

const source = readFileSync(new URL('../src/views/domestic/components/DomesticOrderEditDialog.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'delete-test', inlineTemplate: true }).content
const tick = async () => { for (let i = 0; i < 8; i++) await Vue.nextTick() }
const wrapper = { setup: (_, { slots }) => () => Vue.h('section', [slots.default?.(), slots.footer?.()]) }
const button = { props: ['disabled', 'loading'], setup: (props, { slots, attrs }) => () => Vue.h('button', { ...attrs, ...props }, slots.default?.()) }

async function mountEditor(t, { status = 0, count = 2, creator = 7, confirm, remove, refreshFails = false } = {}) {
  const calls = [], messages = [], events = [], confirmations = []
  let order = { id: 20, domestic_no: 'DO-20', created_by: creator, status, order_kind: 'business',
    order_date: '2026-09-22', remark: 'original', items: Array.from({ length: count }, (_, i) => ({
      id: i + 1, line_code: `A${i + 1}`, product_name: '测试产品', order_qty: 2, unit_price: 50, status: 0,
    })) }
  let reads = 0
  const api = {
    DETAIL_SECTIONS: [], PRODUCT_TYPE_LABELS: {},
    getOptions: async () => ({ data: {} }),
    getOrder: async id => {
      calls.push(['get', id])
      if (++reads > 1 && refreshFails) throw new Error('refresh unavailable')
      return { data: structuredClone(order) }
    },
    deleteOrderItem: async id => {
      calls.push(['delete', id])
      if (remove) await remove()
      order.items = order.items.filter(item => item.id !== id)
    },
  }
  const modules = {
    vue: Vue, 'element-plus': { ElMessage: { success: msg => messages.push(msg), warning: msg => messages.push(msg) },
      ElMessageBox: { confirm: async (...args) => { confirmations.push(args); if (confirm) await confirm() } } },
    '@/api/domestic': api, '@/stores/auth': { useAuthStore: () => ({ user: { id: 7 } }) },
    '@/utils/datetime': { beijingCalendarDate: () => new Date('2026-09-22T00:00:00+08:00') },
    '../domesticOrderEditing': editing, '../domesticAttributeRules': attributes,
    '../domesticOrderKinds': kinds, '../composables/latestRequest': latest,
  }
  const code = compiled.replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, bindings, path) => {
    const binding = bindings.trim().startsWith('{') ? bindings.replace(/\bas\b/g, ':') : `{ default: ${bindings} }`
    modules[path] ??= { default: path.endsWith('GlassButton.vue') ? button : wrapper }
    return `const ${binding} = modules[${JSON.stringify(path)}];`
  }).replace('export default', 'return')
  const component = new Function('modules', code)(modules)
  const renderer = Vue.createRenderer({
    createElement: type => ({ type, children: [], props: {} }), createText: text => ({ text }), createComment: () => ({}),
    insert(child, parent, anchor) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child); child.parent = parent
    },
    remove(child) { child.parent.children.splice(child.parent.children.indexOf(child), 1) },
    patchProp(node, key, _, value) { node.props[key] = value },
    setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
    parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const root = { children: [] }
  const app = renderer.createApp(component, { modelValue: true, orderId: 20, onSaved: () => events.push('saved') })
  for (const name of ['el-dialog', 'el-form', 'el-form-item', 'el-input', 'el-input-number', 'el-select', 'el-option', 'el-date-picker']) app.component(name, wrapper)
  for (const name of ['permission', 'loading']) app.directive(name, {})
  app.mount(root)
  t.after(() => app.unmount())
  await tick()
  const text = node => [node.text || '', ...(node.children || []).map(text)].join('')
  const find = (node, label) => [ ...(node.type === 'button' && text(node) === label ? [node] : []), ...(node.children || []).flatMap(child => find(child, label)) ]
  return { buttons: label => find(root, label), calls, messages, events, confirmations, text: () => text(root) }
}

test('order editor exposes delete; confirmation removes the selected persisted item and refreshes the parent', async t => {
  const ui = await mountEditor(t)
  assert.equal(ui.buttons('删除明细').length, 2)
  await ui.buttons('删除明细')[0].props.onClick()
  await tick()
  assert.deepEqual(ui.calls, [['get', 20], ['delete', 1], ['get', 20]])
  assert.deepEqual(ui.events, ['saved'])
  assert.match(ui.text(), /A2/)
  assert.doesNotMatch(ui.text(), /A1/)
  assert.ok(ui.buttons('删除明细')[0].props.disabled)
})

test('cancelling confirmation keeps all items and sends no delete', async t => {
  const ui = await mountEditor(t, { confirm: async () => { throw 'cancel' } })
  assert.equal(ui.buttons('删除明细').length, 2)
  await ui.buttons('删除明细')[0].props.onClick()
  assert.deepEqual(ui.calls, [['get', 20]])
  assert.deepEqual(ui.events, [])
  assert.equal(ui.messages.length, 0)
})

test('server rejection preserves the row and unlocks controls', async t => {
  const ui = await mountEditor(t, { remove: async () => { throw new Error('已有报工记录') } })
  assert.equal(ui.buttons('删除明细').length, 2)
  await ui.buttons('删除明细')[0].props.onClick()
  await tick()
  assert.match(ui.text(), /A1/)
  assert.equal(ui.buttons('删除明细')[0].props.disabled, false)
  assert.deepEqual(ui.events, [])
  assert.equal(ui.messages.length, 0)
})

test('confirmation locks repeated delete clicks and sibling mutations', async t => {
  let release
  const ui = await mountEditor(t, { confirm: () => new Promise(resolve => { release = resolve }) })
  assert.equal(ui.buttons('删除明细').length, 2)
  const handler = ui.buttons('删除明细')[0].props.onClick
  const pending = handler()
  await tick()
  assert.ok(ui.buttons('编辑明细').every(node => node.props.disabled))
  assert.ok(ui.buttons('添加明细')[0].props.disabled)
  await handler()
  assert.equal(ui.confirmations.length, 1)
  release(); await pending
  assert.equal(ui.calls.filter(([action]) => action === 'delete').length, 1)
})

for (const options of [{ count: 1 }, { status: 3 }, { status: 4 }, { status: 5 }, { status: 6 }, { creator: 8 }]) {
  test(`ineligible deletion is unavailable: ${JSON.stringify(options)}`, async t => {
    const ui = await mountEditor(t, options)
    assert.ok(ui.buttons('删除明细').length > 0)
    assert.ok(ui.buttons('删除明细').every(node => node.props.disabled))
  })
}

test('successful delete remains removed if the follow-up read fails', async t => {
  const ui = await mountEditor(t, { refreshFails: true })
  assert.equal(ui.buttons('删除明细').length, 2)
  await ui.buttons('删除明细')[0].props.onClick()
  await tick()
  assert.doesNotMatch(ui.text(), /A1/)
  assert.deepEqual(ui.events, ['saved'])
})

test('submitted order confirmation explains balance settlement', async t => {
  const ui = await mountEditor(t, { status: 1 })
  assert.equal(ui.buttons('删除明细').length, 2)
  await ui.buttons('删除明细')[0].props.onClick()
  assert.match(ui.confirmations[0][0], /余额/)
})
