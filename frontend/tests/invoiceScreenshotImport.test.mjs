import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildInvoicePayload,
  emptyInvoiceForm,
  INVOICE_NO_MAX_LENGTH,
  screenshotInvoiceNo,
  screenshotOrderName,
} from '../src/views/invoice/composables/invoiceEditorState.js'

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
  assert.match(component, />运费 <strong>\{\{ money\(preview\.fees\.shipping_fee\) \}\}/)
  assert.match(component, />手续费 <strong>\{\{ money\(preview\.fees\.handling_fee\) \}\}/)
  assert.match(component, />包装费 <strong>\{\{ money\(preview\.fees\.packaging_fee\) \}\}/)
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
  assert.match(editor, /resetForm\(\{ \.\.\.patch, invoice_no: invoiceNo, id: null \}\)/)
  assert.match(editor, /invoiceNoEdited = Boolean\(invoiceNo\)/)
  assert.match(editor, /if \(!invoiceNo\) fetchSuggestedInvoiceNo\(\)/)
})


test('recognized order name becomes the screenshot invoice number', () => {
  assert.equal(screenshotInvoiceNo({
    extraction: { order_name: '  凯丽比努尔#260808  ' },
    invoice_patch: { source_order_name: 'fallback' },
  }), '凯丽比努尔#260808')

  assert.equal(screenshotInvoiceNo({
    invoice_patch: { source_order_name: 'fallback order name' },
  }), 'fallback order name')

  assert.equal(screenshotOrderName({
    extraction: { order_name: '   ' },
    invoice_patch: { source_order_name: ' whitespace fallback ' },
  }), 'whitespace fallback')

  assert.equal(
    screenshotInvoiceNo({ extraction: { order_name: 'A'.repeat(INVOICE_NO_MAX_LENGTH + 1) } }).length,
    INVOICE_NO_MAX_LENGTH,
  )
})


test('external OKKI screenshots may sync and are checked for duplicates by backend', () => {
  assert.match(view, /来自外部 OKKI 截图/)
  assert.doesNotMatch(view, /:disabled="row\.source_type === 'okki_screenshot'"/)
  assert.doesNotMatch(view, /:sync-blocked="form\.source_type === 'okki_screenshot'"/)
  assert.doesNotMatch(editor, /if \(form\.source_type === 'okki_screenshot'\)/)
  assert.doesNotMatch(page, /invoice\.source_type !== 'okki_screenshot'/)
  assert.match(editor, /escapeHtml/)
  assert.match(view, /处理待核对/)
  assert.match(api, /sync-uncertain\/resolve/)
  assert.match(footer, /syncBlockedReason/)
})
