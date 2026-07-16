import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const invoiceView = readFileSync(
  new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url),
  'utf8',
)
const invoiceStyles = readFileSync(
  new URL('../src/views/invoice/invoice-manage.css', import.meta.url),
  'utf8',
)

test('invoice editor uses one 36px control height instead of mixed size variants', () => {
  const invoiceFormTag = invoiceView.match(/<el-form\b[^>]*class="invoice-form"[^>]*>/s)?.[0]
  assert.ok(invoiceFormTag, 'invoice form tag should exist')
  assert.doesNotMatch(invoiceFormTag, /\bsize=/)
  assert.match(invoiceStyles, /\.invoice-form\s*{[^}]*--el-component-size:\s*36px;/s)
  assert.match(invoiceStyles, /\.invoice-form\s+:deep\(\.el-input__wrapper\)[\s\S]*min-height:\s*36px;/)
  assert.match(invoiceStyles, /\.invoice-form\s+:deep\(\.el-textarea__inner\)[^{]*{[^}]*min-height:\s*36px\s*!important;/s)
})

test('invoice editor caps desktop field widths and releases them on narrow screens', () => {
  const expectedCaps = [
    ['span-1', '180px'],
    ['span-2', '360px'],
    ['span-3', '560px'],
    ['span-6', '720px'],
  ]

  for (const [span, width] of expectedCaps) {
    assert.match(
      invoiceStyles,
      new RegExp(`\\.head-grid \\.${span} :deep\\(\\.el-form-item__content\\) \\{ max-width: ${width}; \\}`),
    )
  }

  assert.match(
    invoiceStyles,
    /@media \(max-width: 560px\)[\s\S]*\.head-grid \.span-1 :deep\(\.el-form-item__content\),[\s\S]*\.head-grid \.span-6 :deep\(\.el-form-item__content\)\s*{[^}]*max-width:\s*none;/,
  )
})

test('invoice editor keeps metadata in a readable canvas on wide screens', () => {
  assert.match(invoiceStyles, /\.head-section\s*{[^}]*max-width:\s*1400px;/s)
  assert.match(invoiceStyles, /\.col-title\s*{[^}]*font-size:\s*14px;/s)
  assert.match(invoiceView, /<el-form-item label="运费" class="span-2">/)
})

test('unbound OKKI guidance is concise helper text rather than a warning pill', () => {
  assert.match(invoiceView, /class="binding-helper"/)
  assert.match(invoiceView, /未绑定 OKKI，私海筛选无结果/)
  assert.doesNotMatch(invoiceView, /class="rule-badge warn"/)
  assert.match(invoiceStyles, /\.binding-helper\s*{[^}]*line-height:\s*1\.5;/s)
})
