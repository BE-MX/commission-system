import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { buildInvoicePayload, emptyInvoiceForm } from '../src/views/invoice/composables/invoiceEditorState.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const view = read('../src/views/invoice/InvoiceManage.vue')
const component = read('../src/views/invoice/components/InvoiceScreenshotImport.vue')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')
const page = read('../src/views/invoice/composables/useInvoiceManagePage.js')
const api = read('../src/api/invoice.js')
const footer = read('../src/views/invoice/components/InvoiceTotalsFooter.vue')


test('AI screenshot flow has upload, clipboard, preview, and resolve endpoints', () => {
  assert.match(view, /AI 识别 OKKI 截图/)
  assert.match(view, /InvoiceScreenshotImport/)
  assert.match(component, /image\/png,image\/jpeg,image\/webp/)
  assert.match(component, /onPaste/)
  assert.match(component, /navigator\.clipboard/)
  assert.match(component, /preview\.blockers/)
  assert.match(component, /productSelections/)
  assert.match(component, /preview\.ready/)
  assert.match(api, /\/import\/screenshot\/preview/)
  assert.match(api, /\/import\/screenshot\/resolve/)
  assert.match(api, /\/import\/screenshot\/create/)
  assert.match(editor, /createInvoiceFromScreenshot/)
  assert.match(component, /v-if="row\.candidates\?\.length"/)
  assert.match(component, /v-if="orderType === 'production' && row\.can_create_custom"/)
})


test('screenshot provenance survives editor submission', () => {
  const form = {
    ...emptyInvoiceForm(),
    customer_id: '105720449849411',
    customer_name: 'hair_madebymads',
    invoice_date: '2026-08-25',
    source_type: 'okki_screenshot',
    source_order_id: '105724678036852',
    source_order_no: '25278',
    source_order_name: '凯丽比努尔#260808',
    source_image_sha256: 'a'.repeat(64),
    source_preview_token: 'signed-preview-token',
  }

  const payload = buildInvoicePayload(form, 0)

  assert.equal(payload.source_type, 'okki_screenshot')
  assert.equal(payload.source_order_id, '105724678036852')
  assert.equal(payload.source_image_sha256, 'a'.repeat(64))
  assert.equal(payload.source_preview_token, 'signed-preview-token')
  assert.match(editor, /applyScreenshotPreview/)
  assert.match(editor, /resetForm\(\{ \.\.\.patch, invoice_no: '', id: null \}\)/)
})


test('existing OKKI source is visibly and mechanically excluded from sync', () => {
  assert.match(view, /OKKI已存在/)
  assert.match(view, /:disabled="row\.source_type === 'okki_screenshot'"/)
  assert.match(view, /:sync-blocked="form\.source_type === 'okki_screenshot'"/)
  assert.match(editor, /if \(form\.source_type === 'okki_screenshot'\)/)
  assert.match(page, /invoice\.source_type !== 'okki_screenshot'/)
  assert.match(footer, /syncBlockedReason/)
})
