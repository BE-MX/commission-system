import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const invoiceView = readFileSync(
  new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url),
  'utf8',
)
const orderFields = readFileSync(
  new URL('../src/views/invoice/components/InvoiceOrderCustomerFields.vue', import.meta.url),
  'utf8',
)
const invoiceStyles = readFileSync(
  new URL('../src/views/invoice/invoice-manage.css', import.meta.url),
  'utf8',
)
const overviewStyles = readFileSync(
  new URL('../src/views/invoice/components/invoice-overview.css', import.meta.url),
  'utf8',
)
const legacyDrawer = readFileSync(
  new URL('../src/views/invoice/components/legacy/InvoiceLegacyDrawer.vue', import.meta.url),
  'utf8',
)
const settlementFields = readFileSync(
  new URL('../src/views/invoice/components/InvoiceSettlementFields.vue', import.meta.url),
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

test('drawer body splits into two independently scrolling panes', () => {
  assert.match(invoiceView, /<div class="drawer-panes">/)
  assert.match(invoiceView, /<main class="pane pane-main">/)
  assert.match(invoiceView, /<aside class="pane pane-side">/)
  assert.match(invoiceStyles, /\.drawer-panes\s*{[^}]*display:\s*grid/s)
  assert.match(invoiceStyles, /\.drawer-panes\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*372px/s)
  assert.match(invoiceStyles, /\.pane\s*{[^}]*overflow-y:\s*auto/s)
  // 仅新版抽屉 body 不滚动；旧版表单依赖 Drawer body 自身滚动到明细
  assert.match(invoiceView, /body-class="invoice-modern-drawer-body"/)
  assert.match(invoiceStyles, /\.invoice-page\s+:deep\(\.invoice-modern-drawer-body\)[^}]*overflow:\s*hidden/s)
  assert.doesNotMatch(invoiceStyles, /\.invoice-page\s+:deep\(\.el-drawer__body\)/)
  assert.doesNotMatch(legacyDrawer, /invoice-modern-drawer-body/)
  // 窄屏降级为单栏整页滚动
  assert.match(invoiceStyles, /@media \(max-width: 1200px\)[\s\S]*\.drawer-panes\s*{[^}]*grid-template-columns:\s*1fr/s)
})

test('side pane cards keep natural height so fee summary is not clipped', () => {
  // flex 默认会把超高卡片压扁，金额汇总上下被裁（2026-09-25）
  assert.match(invoiceStyles, /\.pane\s*>\s*\*\s*{[^}]*flex:\s*0\s*0\s*auto/s)
  // KPI 卡样式不得串到右栏金额汇总卡
  assert.match(overviewStyles, /\.summary-grid\s+\.summary-card\s*{/)
  assert.doesNotMatch(invoiceStyles + overviewStyles, /(?<!\.summary-grid\s)\.summary-card\s*{[^}]*justify-content:\s*center/s)
  // 金额汇总卡与结算/回款卡同级白卡
  assert.match(invoiceView, /<InvoiceSummaryCard\s+class="form-card"/)
})

test('order entry uses card sections with a three-column top-label grid', () => {
  assert.match(invoiceStyles, /\.form-card\s*{[^}]*border-radius:\s*var\(--card-radius\)/s)
  assert.match(invoiceStyles, /\.invoice-order-fields :deep\(\.card-title\)\s*{[^}]*font-size:\s*14px/s)
  assert.match(invoiceStyles, /\.invoice-order-fields :deep\(\.fgrid\)\s*{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/s)
  assert.match(invoiceView, /label-position="top"/)
  assert.match(invoiceView, /<InvoiceOrderCustomerFields/)
  assert.match(orderFields, /<span class="step">1<\/span>订单与客户/)
  assert.match(settlementFields, /label="运费"/)
})

test('redesigned drawer keeps the agreed entry rules', () => {
  // 客户等级必填
  assert.match(orderFields, /<el-form-item label="客户等级" required>/)
  // 联系人/电话/邮箱/收货地址必填
  assert.match(orderFields, /<el-form-item label="联系人" required>/)
  assert.match(orderFields, /<el-form-item label="电话" required>/)
  assert.match(orderFields, /<el-form-item label="邮箱" required>/)
  assert.match(orderFields, /<el-form-item label="收货地址" required/)
  // 发票号 → 订单号/发票号；日期 → 下单日期
  assert.match(orderFields, /label="订单号\/发票号"/)
  assert.match(orderFields, /label="下单日期" required/)
  // 业务员信息只读资料条
  assert.match(orderFields, /class="fgrid-c3 sales-readout"/)
  assert.match(orderFields, /\{\{ form\.sales_user_name \|\| '—' \}\}/)
})

test('logistics and remark card sits below the accessory card with gold remark styling', () => {
  const accessoryIndex = invoiceView.indexOf('<InvoiceAccessoryTable')
  const logisticsIndex = invoiceView.indexOf('物流与备注')
  assert.ok(accessoryIndex >= 0 && logisticsIndex > accessoryIndex, '物流与备注卡应位于配件明细卡之后')
  assert.match(invoiceView, /<span class="step">4<\/span>物流与备注/)
  assert.match(invoiceView, /备注内容将自动带入到出库单中/)
  // 订单号旁的红色「上一单」提醒
  assert.match(orderFields, /class="prev-order-tip"/)
  assert.match(invoiceStyles, /\.invoice-order-fields :deep\(\.prev-order-tip\)\s*{[^}]*color:\s*var\(--color-danger\)/s)
  // 备注：深金色加粗字体 + 深金色加粗边框
  assert.match(invoiceStyles, /\.remark-gold :deep\(\.el-textarea__inner\)\s*{[^}]*border:\s*2px solid var\(--color-gold-muted\)/s)
  assert.match(invoiceStyles, /\.remark-gold :deep\(\.el-textarea__inner\)\s*{[^}]*font-weight:\s*700/s)
})

test('unbound OKKI guidance is concise helper text rather than a warning pill', () => {
  assert.match(orderFields, /class="binding-helper"/)
  assert.match(orderFields, /未绑定 OKKI，私海筛选无结果/)
  assert.doesNotMatch(orderFields, /class="rule-badge warn"/)
  assert.match(invoiceStyles, /\.invoice-order-fields :deep\(\.binding-helper\)\s*{[^}]*line-height:\s*1\.5;/s)
})
