import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import { formatMoney } from '../src/utils/money.js'

// Render the actual amount cell template without mounting the unrelated editor.
const source = readFileSync(new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url), 'utf8')
const cell = source.match(/<template v-else-if="column.key === 'order_amount'[\s\S]*?<\/template>/)?.[0]
assert.ok(cell, 'invoice amount cell must exist')
const { code } = compile(cell.replace('v-else-if=', 'v-if='), { mode: 'function', prefixIdentifiers: true })
const render = new Function('Vue', code)(Vue)

for (const key of ['order_amount', 'total_amount']) {
  test(`${key} renders its amount without a USD prefix and retains other currencies`, async () => {
    for (const currency of ['USD', 'usd', 'EUR']) {
      const html = await renderToString(Vue.createSSRApp({
        render,
        data: () => ({ column: { key }, row: { currency, order_amount: 1234.56, total_amount: 1254.81 }, money: formatMoney }),
      }))
      assert.ok(html.includes(formatMoney(key === 'order_amount' ? 1234.56 : 1254.81)))
      assert.doesNotMatch(html, /usd/i)
      assert.equal(html.includes('EUR'), currency === 'EUR')
    }
  })
}

for (const [key, expected, other] of [['order_amount', '1,234.56', '1,254.81'], ['total_amount', '1,254.81', '1,234.56']]) {
  test(`${key} stays in its own single-line column`, async () => {
    const html = await renderToString(Vue.createSSRApp({
      render,
      data: () => ({ column: { key }, row: { currency: 'EUR', order_amount: 1234.56, total_amount: 1254.81 }, money: formatMoney }),
    }))
    assert.ok(html.includes(expected))
    assert.ok(!html.includes(other))
    assert.equal((html.match(/EUR/g) || []).length, 1)
    assert.doesNotMatch(html, /invoice-pair/)
  })
}
