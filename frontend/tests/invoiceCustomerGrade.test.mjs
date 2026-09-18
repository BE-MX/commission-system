import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { emptyInvoiceForm, buildInvoicePayload } from '../src/views/invoice/composables/invoiceEditorState.js'
import { buildOutboundDoc } from '../src/views/shipping/print/printDocs.js'

const editor = readFileSync(new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url), 'utf8')
const start = editor.indexOf('  async function fillContactDefaults()')
const end = editor.indexOf('  // 编辑回显专用', start)
function harness(request) {
  const form = { customer_id: 'C1', customer_grade: 'A' }
  return new Function('form', 'getCustomerContactDefaults', `
    let contactFillSeq = 0, gradeEditSeq = 0, customerGradeReady = true;
    const okkiFlagsTouched = { newDeal: false }, lastOrderDate = { value: '' };
    ${editor.slice(start, end)}
    return { form, fillContactDefaults, ready: () => customerGradeReady,
      change: grade => { gradeEditSeq++; customerGradeReady = true; form.customer_grade = grade } };
  `)(form, request)
}

test('new invoice starts empty and payload preserves selected grade', () => {
  const form = emptyInvoiceForm()
  assert.equal(form.customer_grade, null)
  for (const grade of ['S', 'A', 'B', 'C', 'D', null]) {
    form.customer_grade = grade
    assert.equal(buildInvoicePayload(form, 0).customer_grade, grade)
  }
})

test('customer switch clears old grade and ignores stale response', async () => {
  const resolve = []
  const h = harness(() => new Promise(done => resolve.push(done)))
  const first = h.fillContactDefaults()
  assert.equal(h.form.customer_grade, null)
  h.form.customer_id = 'C2'
  const second = h.fillContactDefaults()
  resolve[1]({ customer_grade: 'B' }); await second
  resolve[0]({ customer_grade: 'S' }); await first
  assert.equal(h.form.customer_grade, 'B')
})

for (const edited of ['D', null]) {
  test(`manual edit ${edited} survives late defaults`, async () => {
    let resolve
    const h = harness(() => new Promise(done => { resolve = done }))
    const pending = h.fillContactDefaults()
    h.change(edited)
    resolve({ customer_grade: 'S' }); await pending
    assert.equal(h.form.customer_grade, edited)
  })
}

test('failed defaults does not authorize clearing stored grade', async () => {
  const h = harness(async () => { throw Error('offline') })
  await h.fillContactDefaults()
  assert.equal(h.ready(), false)
  h.change('C')
  assert.equal(h.ready(), true)
})

test('outbound print has grade and currency amount on customer row and escapes data', () => {
  const html = buildOutboundDoc({ record: { customer_name: 'Customer', customer_grade: 'S', order_amount_text: 'EUR 1,234.50' } })
  assert.match(html, /Cus\*\*\*.*客户等级<br>S.*订单金额<br>EUR 1,234.50/)
  const escaped = buildOutboundDoc({ record: { customer_grade: '<script>', order_amount_text: '<img>' } })
  assert.ok(!escaped.includes('<script>'))
  assert.ok(escaped.includes('&lt;img&gt;'))
  assert.match(buildOutboundDoc({ record: {} }), /订单金额<br>—/)
})
