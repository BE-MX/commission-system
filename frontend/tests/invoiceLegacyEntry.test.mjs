import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const view = read('../src/views/invoice/InvoiceManage.vue')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')
const legacyDrawer = read('../src/views/invoice/components/legacy/InvoiceLegacyDrawer.vue')
const legacySettlement = read('../src/views/invoice/components/legacy/InvoiceLegacySettlementFields.vue')
const legacyFooter = read('../src/views/invoice/components/legacy/InvoiceLegacyTotalsFooter.vue')
const legacyReceipt = read('../src/views/invoice/components/legacy/InvoiceLegacyReceiptFields.vue')

test('legacy create entry coexists with the redesigned drawer', () => {
  // 新版为默认入口，旧版入口下拉提供库存单/生产单
  assert.match(view, /新建库存单/)
  assert.match(view, /旧版入口/)
  assert.match(view, /库存单（旧版）/)
  assert.match(view, /生产单（旧版）/)
  assert.match(view, /@command="openLegacyCreate"/)
  assert.match(view, /<InvoiceLegacyDrawer\s+:editor="editor"/)
  // 整单粘贴对话框两版共用
  assert.match(view, /@open-paste="wholeOrderPasteVisible = true"/)
})

test('editor shares one form state between new and legacy drawers', () => {
  assert.match(editor, /const legacyVisible = ref\(false\)/)
  assert.match(editor, /async function prepareCreate/)
  // 同一套初始化流程，只是打开不同的抽屉
  assert.match(editor, /await prepareCreate\(orderType\)\s*\n\s*drawerVisible\.value = true/)
  assert.match(editor, /await prepareCreate\(orderType\)\s*\n\s*legacyVisible\.value = true/)
})

test('legacy drawer restores the HEAD-era layout with legacy companions', () => {
  assert.match(legacyDrawer, /label-width="80px"/)
  assert.match(legacyDrawer, /业务员信息/)
  assert.match(legacyDrawer, /<InvoiceLegacySettlementFields/)
  assert.match(legacyDrawer, /<InvoiceLegacyReceiptFields/)
  assert.match(legacyDrawer, /<InvoiceLegacyTotalsFooter/)
  assert.match(legacyDrawer, /v-model="legacyVisible"/)
  // 行操作事件不能丢（复制一行/添加空行/删除）
  assert.match(legacyDrawer, /@copy="copyLine"/)
  assert.match(legacyDrawer, /@add-blank="addBlankLine"/)
  assert.match(legacyDrawer, /@remove="removeLine"/)
  // 旧版结算区保留只读推导金额输入框
  assert.match(legacySettlement, /label="头发金额"[\s\S]*readonly[\s\S]*Hair Price/)
  // 旧版页脚保留完整金额链
  for (const label of ['头发金额', '头发折扣', '配件金额', '配件折扣', '包装费用', '运费', '手续费', '应付合计']) {
    assert.ok(legacyFooter.includes(label), `${label} should stay in legacy footer`)
  }
  // 旧版回款：独立小满回款方式下拉（不使用 hide-payment-type）
  assert.doesNotMatch(legacyReceipt, /hide-payment-type/)
  // 旧版明细区保留独立「从 Excel 粘贴」入口
  assert.match(legacyDrawer, /show-paste-entry/)
  assert.match(legacyDrawer, /@paste="\$emit\('open-legacy-paste'\)"/)
  assert.match(view, /@open-legacy-paste="pasteImportVisible = true"/)
})
