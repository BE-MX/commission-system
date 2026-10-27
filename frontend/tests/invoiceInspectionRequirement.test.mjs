import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyInvoiceForm, buildInvoicePayload } from '../src/views/invoice/composables/invoiceEditorState.js'
import { buildOutboundDoc } from '../src/views/shipping/print/printDocs.js'

test('automatic default follows new-deal until a user explicitly chooses', () => {
  const form = emptyInvoiceForm()
  form.okki_new_deal = 0
  assert.equal(buildInvoicePayload(form).inspection_requirement, 'single')
  form.okki_new_deal = 1
  assert.equal(buildInvoicePayload(form).inspection_requirement, 'detail')
  form.inspection_requirement = 'single'
  assert.equal(buildInvoicePayload(form).inspection_requirement, 'single')
  form.okki_new_deal = 0
  form.inspection_requirement = 'detail'
  assert.equal(buildInvoicePayload(form).inspection_requirement, 'detail')
  const reloaded = { ...emptyInvoiceForm(), ...form }
  reloaded.okki_new_deal = 1
  assert.equal(buildInvoicePayload(reloaded).inspection_requirement, 'detail')
  assert.equal(emptyInvoiceForm().inspection_requirement, null)
})

for (const isNew of [false, true]) {
  for (const choice of ['single', 'detail']) {
    test(`outbound marks independently: new=${isNew}, photos=${choice}`, () => {
      const html = buildOutboundDoc({ record: { is_new_deal: isNew, inspection_requirement: choice } })
      const header = html.match(/<div class="header">([\s\S]*?)<div class="body-row">/)[1]
      assert.equal(header.includes('新签'), isNew)
      assert.equal(header.includes('拍摄明细照片'), choice === 'detail')
      assert.match(html, /\.order-marks\{[^}]*font-size:24px;[^}]*font-weight:800/)
    })
  }
}
