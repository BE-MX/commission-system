import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const orders = readFileSync(new URL('../src/views/domestic/DomesticOrders.vue', import.meta.url), 'utf8')
const directive = readFileSync(new URL('../src/directives/permission.js', import.meta.url), 'utf8')

function buttonPermission(label) {
  const button = [...orders.matchAll(/<GlassButton\b((?:"[^"]*"|'[^']*'|[^'">])*)>([^<]*)<\/GlassButton>/g)]
    .find(match => match[2].trim() === label)
  assert.ok(button, `${label} button exists`)
  return button[1].match(/v-permission="'([^']+)'"/)?.[1]
}

for (const [permissions, roles, report, skip] of [
  [['domestic:write', 'domestic:admin'], [], false, false],
  [['domestic_report:write'], [], true, false],
  [['domestic_skip:write'], [], false, true],
  [['domestic_report:write', 'domestic_skip:write'], [], true, true],
  [[], ['super_admin'], true, true],
]) {
  test(`detail buttons follow independent grants: ${permissions.join(',') || roles.join(',')}`, () => {
    const context = {
      useAuthStore: () => ({ hasPermission: code => roles.includes('super_admin') || permissions.includes(code) }),
    }
    const source = directive.replace(/^import .*$/gm, '').replace(/^export /gm, '')
    vm.runInNewContext(`${source}\nthis.permission = vPermission`, context)
    for (const [label, visible] of [['代报工', report], ['异常跳过', skip]]) {
      const el = { style: { display: '' }, dataset: {} }
      context.permission.mounted(el, { value: buttonPermission(label) })
      assert.equal(el.style.display, visible ? '' : 'none')
    }
  })
}
