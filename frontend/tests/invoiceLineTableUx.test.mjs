import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

// 明细表录入体验：核心数字保留最小输入空间与桌面固定列、批量删除/清空
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
    assert.match(source, /label="客户价" min-width="130" align="right"[^>]*:fixed="pinColumns \? 'right' : false"/)
    assert.match(source, /label="数量" min-width="96"[^>]*:fixed="pinColumns \? 'right' : false"/)
    assert.match(source, /label="小计" min-width="110"[^>]*:fixed="pinColumns \? 'right' : false"/)
    assert.match(source, /pinColumns: { type: Boolean, default: true }/)
    assert.match(source, /label="操作" min-width="56" fixed="right"/)
    assert.doesNotMatch(source, /<el-table-column[^>]*(?<![-:])\bwidth="\d+/)
    // max-width 不是 el-table-column 的属性，写了等于没写
    assert.doesNotMatch(source, /<el-table-column[^>]*max-width=/)
  }
})

test('price cell gives the whole width to the number', () => {
  // 手改改用底色 + 悬停提示，不再在格内放标签挤压输入框
  assert.doesNotMatch(hairTable, /StatusBadge[^>]*>手改</)
  assert.doesNotMatch(accessoryTable, /StatusBadge[^>]*>手改</)
  assert.match(hairTable, /`已手改，标准价 \$\{/)
  // 两位显示藏住的小数位要能查到
  assert.match(hairTable, /parts\.push\(`按 \$\{precise\} 计价`\)/)
  assert.match(accessoryTable, /客户价 \$\{preciseMoney\(row\.customer_price\)\}/)
  assert.match(hairTable, /\.price-cell :deep\(input\) { text-align: right; font-variant-numeric: tabular-nums; }/)
  assert.match(hairTable, /<el-input-number class="line-price-input" v-model="row.price_per_piece"/)
  assert.match(hairTable, /\.line-price-input { width: 100%; }/)
  assert.doesNotMatch(hairTable, /\.price-cell :deep\(\.el-input-number\)/)
  // 配件客户参考价移到输入框下方小字
  assert.match(accessoryTable, /\.price-cell { display: flex; flex-direction: column;/)
  assert.match(accessoryTable, /@blur="commitPrice\(row\)"\s*\/>[\s\S]{0,120}?<span class="customer-price-reference"/)
})

test('stock order Product_name collapses to match status with full name on hover', () => {
  assert.match(hairTable, /:label="collapseSpecs \? '产品名称' : '匹配'" :width="collapseSpecs \? undefined : 150"/)
  // 规格列收起后名称是唯一能区分行的信息，必须完整显示
  assert.match(hairTable, /<span v-else-if="collapseSpecs" class="product-name">\{\{ row\.product_name \|\| '待匹配' \}\}<\/span>/)
  // 状态模式下读屏也能读到完整名称
  assert.match(hairTable, /<span class="sr-only">\{\{ row\.product_name \|\| '待匹配' \}\}<\/span>/)
  assert.match(hairTable, /<el-tooltip :disabled="collapseSpecs \|\| !row\.product_name" :content="row\.product_name \|\| ''"/)
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
    assert.match(source, /<el-table-column type="selection" min-width="42" fixed/)
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

test('legacy 640px drawer turns off right pinning', () => {
  // 482px 固定列在 640px 抽屉里只剩约 110px 可滚动（2026-10-12 对抗审查）
  assert.equal((legacyDrawer.match(/:pin-columns="false"/g) || []).length, 2)
  assert.doesNotMatch(invoiceView, /:pin-columns=/)
})

test('price box commits on blur so retyping the same cents still refreshes the line', () => {
  assert.match(hairTable, /@change="onPriceInput\(row\)" @blur="onPriceInput\(row\)"/)
  assert.match(accessoryTable, /@change="commitPrice\(row\)"\s*@blur="commitPrice\(row\)"/)
  assert.match(hairItems, /row\.price_per_piece = snapPriceToRule\(row\.price_per_piece, row\.customer_price\)/)
})

test('snapPriceToRule restores the 4-decimal rule price only when the visible cents match', async () => {
  const { snapPriceToRule, hiddenPricePrecision } = await import('../src/views/invoice/composables/invoiceSettlement.js')
  assert.equal(snapPriceToRule(21.19, 21.1919), 21.1919) // 重输同样的两位：还原规则价
  assert.equal(snapPriceToRule(21.2, 21.1919), 21.2) // 真改了：保留
  assert.equal(snapPriceToRule(30.05, 30.048), 30.048)
  assert.equal(snapPriceToRule(25, null), 25) // 无规则价：原样
  assert.equal(snapPriceToRule(null, 5), null)
  assert.equal(hiddenPricePrecision(21.1919), '21.1919')
  assert.equal(hiddenPricePrecision(30.048), '30.048')
  assert.equal(hiddenPricePrecision(21.19), '')
  assert.equal(hiddenPricePrecision(0.1 + 0.2), '') // 浮点误差不算隐藏小数
  assert.equal(hiddenPricePrecision(null), '')
})

test('selection drops rows replaced by a reload with the same row count', async () => {
  // 保存草稿 / 切换发票会整批换新行对象但行数不变（2026-10-12 对抗审查）
  const Vue = await import('vue')
  const { useLineSelection } = await import('../src/views/invoice/composables/useLineSelection.js')
  const form = Vue.reactive({ items: [{ id: 1 }, { id: 2 }, { id: 3 }] })
  const items = Vue.computed(() => form.items)
  const paged = Vue.computed(() => items.value.slice(0, 20))
  const scope = Vue.effectScope()
  const sel = scope.run(() => useLineSelection(Vue.ref(null), items, paged))
  sel.onSelect([], form.items[0])
  sel.onSelect([], form.items[1])
  assert.equal(sel.selectedCount.value, 2)
  form.items = [{ id: 1 }, { id: 2 }, { id: 3 }]
  await Vue.nextTick()
  assert.equal(sel.selectedCount.value, 0)
  sel.onSelect([], form.items[2])
  form.items = form.items.filter(row => row.id !== 1)
  await Vue.nextTick()
  assert.equal(sel.selectedCount.value, 1)
  scope.stop()
})
