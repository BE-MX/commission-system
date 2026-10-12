import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

// 明细表录入体验（2026-10-12）：价格列够宽、核心数字固定右侧、批量删除/清空
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const hairTable = read('../src/views/invoice/components/InvoiceHairTable.vue')
const accessoryTable = read('../src/views/invoice/components/InvoiceAccessoryTable.vue')
const selection = read('../src/views/invoice/composables/useLineSelection.js')
const hairItems = read('../src/views/invoice/composables/useInvoiceHairItems.js')
const accessories = read('../src/views/invoice/composables/useInvoiceAccessories.js')
const invoiceView = read('../src/views/invoice/InvoiceManage.vue')
const legacyDrawer = read('../src/views/invoice/components/legacy/InvoiceLegacyDrawer.vue')

test('price, quantity, total and action columns stay pinned on the right', () => {
  for (const source of [hairTable, accessoryTable]) {
    assert.match(source, /label="客户价" width="130" align="right"[^>]*fixed="right"/)
    assert.match(source, /label="Quantity" width="96"[^>]*fixed="right"/)
    assert.match(source, /label="TotalPrice" width="110"[^>]*fixed="right"/)
    assert.match(source, /label="操作" width="56" fixed="right"/)
    // max-width 不是 el-table-column 的属性，写了等于没写
    assert.doesNotMatch(source, /<el-table-column[^>]*max-width=/)
  }
})

test('price cell gives the whole width to the number', () => {
  // 手改改用底色 + 悬停提示，不再在格内放标签挤压输入框
  assert.doesNotMatch(hairTable, /StatusBadge[^>]*>手改</)
  assert.doesNotMatch(accessoryTable, /StatusBadge[^>]*>手改</)
  assert.match(hairTable, /`已手改，标准价 \$\{/)
  assert.match(hairTable, /\.price-cell :deep\(input\) { text-align: right; font-variant-numeric: tabular-nums; }/)
  // 配件客户参考价移到输入框下方小字
  assert.match(accessoryTable, /\.price-cell { display: flex; flex-direction: column;/)
  assert.match(accessoryTable, /<\/el-input-number>|\/>\s*<span class="customer-price-reference"/)
})

test('stock order Product_name collapses to match status with full name on hover', () => {
  assert.match(hairTable, /label="匹配" width="130" prop="product_name"/)
  assert.match(hairTable, /<el-tooltip :disabled="!row\.product_name" :content="row\.product_name \|\| ''"/)
  assert.match(hairTable, /row\.product_name \? '已匹配' : '待匹配'/)
})

test('discount column folds away unless a row carries a discount', () => {
  assert.match(hairTable, /const showDiscountCol = computed\(\(\) => showOptionalCols\.value\s*\|\| props\.items\.some\(row => Number\(row\.discount_amount \|\| 0\) !== 0\)\)/)
  assert.match(accessoryTable, /const showDiscountCol = computed\(\(\) => showOptionalCols\.value\s*\|\| props\.items\.some\(row => Number\(row\.discount_amount \|\| 0\) !== 0\)\)/)
  assert.match(hairTable, /v-if="showDiscountCol" label="折扣"/)
  assert.match(accessoryTable, /v-if="showDiscountCol" label="折扣"/)
})

test('both tables support multi-select delete and clear-all with confirmation', () => {
  for (const [source, noun] of [[hairTable, '产品明细'], [accessoryTable, '配件']]) {
    assert.match(source, /<el-table-column type="selection" width="42" fixed/)
    assert.match(source, /@select="onSelect" @select-all="onSelectAll"/)
    assert.match(source, /<template v-if="selectedCount">[\s\S]*?删除所选[\s\S]*?取消选择/)
    assert.match(source, /:disabled="!items\.length" @click="clearAll"/)
    assert.ok(source.includes("confirmDanger('删除', `所选 ${"), 'delete-selected confirm')
    assert.ok(source.includes(` 行${noun}\``), 'confirm names the table')
    assert.ok(source.includes("confirmDanger('清空', `全部 ${props.items.length} 行" + noun + '`'), 'clear-all confirm')
    assert.match(source, /if \(isFeedbackCancelled\(error\)\) return/)
    assert.match(source, /emit\('remove-many', takeSelected\(\)\)/)
    assert.match(source, /emit\('remove-many', \[\.\.\.props\.items\]\)/)
  }
})

test('remove-many is wired through both drawers', () => {
  for (const source of [invoiceView, legacyDrawer]) {
    assert.match(source, /@remove="removeLine"\s*@remove-many="removeLines"/)
    assert.match(source, /@remove="removeAccessory"\s*@remove-many="removeAccessories"/)
  }
  // 按引用过滤：产品行和配件行共用 form.items，只删传入的那些
  assert.match(hairItems, /function removeLines\(rows\) {\s*const doomed = new Set\(rows\)/)
  assert.match(accessories, /function removeAccessories\(rows\) {\s*const doomed = new Set\(rows\)/)
  assert.match(hairItems, /form\.items = form\.items\.filter\(item => !doomed\.has\(item\)\)/)
})

test('selection survives pagination and forgets removed rows', () => {
  assert.match(selection, /watch\(pagedItems, syncTableSelection, { flush: 'post' }\)/)
  assert.match(selection, /table\.toggleRowSelection\(row, selected\.value\.has\(row\)\)/)
  assert.match(selection, /const alive = new Set\(items\.value\)/)
})
