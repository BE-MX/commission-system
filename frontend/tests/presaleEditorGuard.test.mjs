import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'

const source = readFileSync(new URL('../src/views/invoice/components/InvoiceTotalsFooter.vue', import.meta.url), 'utf8')
const compiled = compileScript(parse(source).descriptor, { id: 'presale-footer-test', inlineTemplate: true })
const module = new vm.SourceTextModule(compiled.content)
await module.link(name => {
  const exports = name === 'vue' ? vue : { useAuthStore: () => ({ hasPermission: () => true }) }
  assert.ok(name === 'vue' || name === '@/stores/auth')
  return new vm.SyntheticModule(Object.keys(exports), function () {
    for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
  })
})
await module.evaluate()

async function footer(reason, syncBlocked = false) {
  const app = vue.createSSRApp(module.namespace.default, {
    form: { currency: 'USD', surcharge_amount: 0, presale_edit_blocked_reason: reason },
    total: 627, baseAmount: 627, money: value => String(value), syncBlocked,
    syncBlockedReason: '关联同步未结束',
  })
  app.component('el-button', vue.defineComponent({ props: ['disabled'], setup: (props, { slots }) =>
    () => vue.h('button', { disabled: props.disabled }, slots.default?.()) }))
  app.component('el-tooltip', vue.defineComponent({ props: ['disabled', 'content'], setup: (_, { slots }) => () => slots.default?.() }))
  app.directive('permission', {})
  return renderToString(app)
}

test('active presale explains independent registration and disables both document writes', async () => {
  const reason = '本批未完成；新增到账款请使用右侧“登记预售收款”，提交后无需保存主单。'
  const html = await footer(reason)
  assert.match(html, /登记预售收款/)
  assert.match(html, /无需保存主单/)
  assert.equal((html.match(/<button[^>]*disabled/g) || []).length, 2)
  assert.match(html, /<button[^>]*>取消<\/button>/)
})

test('completed batches re-enable document writes; linked sync still blocks them', async () => {
  assert.equal((await footer(null)).match(/<button[^>]*disabled/g), null)
  assert.equal(((await footer(null, true)).match(/<button[^>]*disabled/g) || []).length, 2)
})
