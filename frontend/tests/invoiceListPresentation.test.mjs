import test from 'node:test'
import assert from 'node:assert/strict'
import { receivedAmountTone } from '../src/views/invoice/invoiceListPresentation.js'
import { readFileSync } from 'node:fs'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import { formatMoney } from '../src/utils/money.js'

test('receipt color compares money at cent precision', () => {
  assert.equal(receivedAmountTone('100.00', 100), 'equal')
  assert.equal(receivedAmountTone(0.1 + 0.2, '0.30'), 'equal')
  assert.equal(receivedAmountTone('100.01', 100), 'overpaid')
  assert.equal(receivedAmountTone('99.99', 100), 'underpaid')
  assert.equal(receivedAmountTone(0, 100), 'underpaid')
  assert.equal(receivedAmountTone(0, 0), 'equal')
  assert.equal(receivedAmountTone('1.005', '1.00'), 'overpaid')
  assert.equal(receivedAmountTone('111.005', '111.00'), 'overpaid')
  assert.equal(receivedAmountTone('-1.005', '-1.00'), 'underpaid')
  assert.equal(receivedAmountTone(1e-7, 0), 'equal')
})

test('missing or invalid finance values remain unverified rather than showing zero', () => {
  for (const value of [undefined, null, '', ' ', 'invalid', Infinity, true]) {
    assert.equal(receivedAmountTone(value, 100), 'unknown')
    assert.equal(receivedAmountTone(100, value), 'unknown')
  }
})

const source = readFileSync(new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url), 'utf8')
const cell = source.match(/<template v-else-if="column.key === 'received_amount'">[\s\S]*?<\/template>/)?.[0]
assert.ok(cell)
const { code } = compile(cell.replace('v-else-if=', 'v-if='), { mode: 'function', prefixIdentifiers: true })
const render = new Function('Vue', code)(Vue)

for (const [amount, tone, text] of [[100, 'equal', '100.00'], [101, 'overpaid', '101.00'], [100.005, 'overpaid', '100.01'], [0, 'underpaid', '0.00'], [null, 'unknown', '—']]) {
  test(`received amount renders ${tone} without inventing missing financial data`, async () => {
    const html = await renderToString(Vue.createSSRApp({
      render,
      data: () => ({ column: { key: 'received_amount' }, row: { received_amount: amount, total_amount: 100, currency: 'USD' }, money: formatMoney, receivedAmountTone }),
    }))
    assert.ok(html.includes(`invoice-received--${tone}`))
    assert.ok(html.includes(text))
    if (tone === 'unknown') assert.ok(!html.includes('0.00'))
  })
}
