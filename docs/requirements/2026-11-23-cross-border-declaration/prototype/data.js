// 跨境申报核对 · 原型示例数据：部分订单号/运单号/金额取自 2026-11 样本并改编，不含客户姓名、电话、地址
// 每条记录 = 一条 DHL 申报（订单头 + 本行明细 + 收款单）与它配对上的「票」。

export const imports = [
  { kind: 'order', name: '订单1795398200619.xls', at: '2026-11-23 09:43', rows: 37, added: 12, existed: 25, suspected: 1 },
  { kind: 'receipt', name: '收款单1795405261021.xls', at: '2026-11-23 11:41', rows: 10, added: 3, existed: 7, suspected: 0 },
]

// 异常字典：level = block（阻断导出）/ remind（提醒）
export const ISSUES = {
  no_invoice:      { label: '申报无发票',     level: 'block',  hint: '方舟里没有这个阿里订单号的 DHL9610 发票。确认发票是否已开、阿里订单号是否录对。' },
  no_waybill:      { label: '申报无运单',     level: 'block',  hint: '发票已开，但验货单还没上传物流单。' },
  amount_mismatch: { label: '金额对不上',     level: 'block',  hint: '申报货值必须等于这一票的应付合计，不允许差额。请业务员核对发票或在 DHL 修改申报。' },
  split_floor:     { label: '分票低于产品金额', level: 'block', hint: '分票发货时，本票申报不能低于本票出库产品金额（出库数量 × 发票净单价）。' },
  split_total:     { label: '分票合计不符',   level: 'block',  hint: '这张发票已全部发完，各票申报之和必须等于应付合计。' },
  ambiguous:       { label: '配对歧义',       level: 'block',  action: 'assign', hint: '这条申报既能配给整发的票，也可能属于分票的票。请指定对应哪一票。' },
  no_receipt:      { label: '缺收款单',       level: 'block',  hint: '还没导入这条申报的收款单。导入最新的 DHL 收款单文件即可。' },
  not_picked:      { label: '未揽收',         level: 'block',  action: 'confirm_shipped', hint: 'DHL 还没有揽收事件。货若已交给 DHL，可确认已发后放行。' },
  invoice_cancelled: { label: '发票已取消',   level: 'block',  hint: '对应发票已取消，不要在 DHL 侧提交这条申报。' },
  split_pending:   { label: '分票未发完',     level: 'remind', hint: '这张发票还有货没发，合计等全部发完后再校验，不影响本票报关。' },
  unit:            { label: '单位不统一',     level: 'remind', hint: '计量单位不是「条」(015)。' },
  suspected:       { label: '可能已被修改',   level: 'remind', action: 'void', hint: '最新导出里没有这条旧申报，可能在 DHL 改过。导出时需确认；确认改过可作废旧条目。' },
}

export const SHOPS = ['大莱莎', '小莱莎', '新莱莎']

export const LOGISTICS = {
  not_picked: { label: '未揽收', tone: 'neutral' },
  picked:     { label: '已揽收', tone: 'info' },
  transit:    { label: '运输中', tone: 'info' },
  customs:    { label: '清关中', tone: 'warning' },
  delivered:  { label: '已签收', tone: 'success' },
  none:       { label: '—', tone: 'neutral' },
}

const line = (qty, price, unit = '015') => ({ itemName: '100% 人发假发', unit, qty, price, total: +(qty * price).toFixed(3) })

export const records = [
  {
    id: 'd01', orderNo: '323144766001020706', shop: '大莱莎', sales: '宋化通', boundAt: '2026-11-20 15:02',
    goodsValue: '2331.04000', freight: '90.00000', line: line(17, 137.12),
    receipt: { charge: '2331.04000', accountingDate: '2026-11-20 16:03:37' },
    ticket: { waybill: '9504745001', logistics: 'transit', pickedAt: '2026-11-20 18:20', kind: 'exact', amount: 2331.04,
      invoices: [{ no: 'SHT261102', total: 2331.04, product: 2245.04, fees: 86.00 }] },
    issues: [], exported: false,
  },
  {
    id: 'd02', orderNo: '36360012501044850', shop: '大莱莎', sales: '宋化通', boundAt: '2026-11-19 10:41',
    goodsValue: '3013.92000', freight: '80.00000', line: line(13, 231.84),
    receipt: { charge: '3013.92000', accountingDate: '2026-11-19 09:12:05' },
    ticket: { waybill: '9504745353', logistics: 'delivered', pickedAt: '2026-11-19 17:05', kind: 'exact', amount: 2953.78,
      invoices: [{ no: 'SHT261131', total: 2953.78, product: 2817.75, fees: 136.03 }] },
    issues: ['amount_mismatch'], exported: false,
  },
  {
    id: 'd03', orderNo: '321221203501027340', shop: '小莱莎', sales: '胡宁宁', boundAt: '2026-11-23 10:15',
    goodsValue: '1097.30000', freight: '50.00000', line: line(8, 137.1625),
    receipt: { charge: '1097.30000', accountingDate: '2026-11-23 08:40:11' },
    ticket: { waybill: '7923101476', logistics: 'not_picked', pickedAt: null, kind: 'exact', amount: 1097.30,
      invoices: [{ no: 'SHT261187', total: 1097.30, product: 1040.30, fees: 57.00 }] },
    issues: ['not_picked'], exported: false,
  },
  {
    id: 'd04', orderNo: '322655386001022993', shop: null, sales: null, boundAt: null,
    goodsValue: '322.77000', freight: '40.00000', line: line(1, 322.77),
    receipt: { charge: '322.77000', accountingDate: '2026-11-22 14:30:00' },
    ticket: null,
    issues: ['no_invoice'], exported: false,
  },
  {
    id: 'd05', orderNo: '322088631001023624', shop: '新莱莎', sales: '田雯', boundAt: '2026-11-23 09:20',
    goodsValue: '304.49000', freight: '40.00000', line: line(2, 152.245),
    receipt: null,
    ticket: { waybill: '9402041622', logistics: 'picked', pickedAt: '2026-11-23 11:02', kind: 'exact', amount: 304.49,
      invoices: [{ no: 'SHT261190', total: 304.49, product: 262.49, fees: 42.00 }] },
    issues: ['no_receipt'], exported: false,
  },
  {
    id: 'd06', orderNo: '322844698001022094', shop: '小莱莎', sales: '李娜', boundAt: '2026-11-21 16:48',
    goodsValue: '1380.00000', freight: '55.00000', line: line(7, 197.142857),
    receipt: { charge: '1380.00000', accountingDate: '2026-11-21 10:05:44' },
    ticket: { waybill: '2002786516', logistics: 'transit', pickedAt: '2026-11-21 19:30', kind: 'split', floor: 1320.00, amount: null,
      split: { invoice: 'SHT261150', invoiceTotal: 2196.28, shippedQty: 7, invoiceQty: 11, otherTickets: [] },
      invoices: [{ no: 'SHT261150', total: 2196.28, product: 2074.28, fees: 122.00 }] },
    issues: ['split_pending'], exported: false,
  },
  {
    id: 'd07', orderNo: '323118722001025565', shop: '大莱莎', sales: '王磊', boundAt: '2026-11-22 11:30',
    goodsValue: '590.00000', freight: '60.00000', line: line(4, 147.5),
    receipt: { charge: '590.00000', accountingDate: '2026-11-22 09:18:20' },
    ticket: { waybill: '7006527942', logistics: 'picked', pickedAt: '2026-11-22 17:44', kind: 'split', floor: 600.00, amount: null,
      split: { invoice: 'SHT261162', invoiceTotal: 1500.00, shippedQty: 6, invoiceQty: 15, otherTickets: [] },
      invoices: [{ no: 'SHT261162', total: 1500.00, product: 1440.00, fees: 60.00 }] },
    issues: ['split_floor'], exported: false,
  },
  {
    id: 'd08', orderNo: '322444758001022514', shop: '大莱莎', sales: '刘洋', boundAt: '2026-11-22 15:12',
    goodsValue: '163.00000', freight: '40.00000', line: line(1, 163),
    receipt: { charge: '163.00000', accountingDate: '2026-11-22 13:01:09' },
    ticket: { waybill: '7006551926', logistics: 'transit', pickedAt: '2026-11-22 18:10', kind: 'exact', amount: 163.00,
      invoices: [{ no: 'SHT261171', total: 163.00, product: 118.23, fees: 44.77 }] },
    candidates: [
      { waybill: '7006551926', kind: '整发', amount: '163.00', invoices: 'SHT261171' },
      { waybill: '7006559910', kind: '分票', amount: '下限 150.00', invoices: 'SHT261168' },
    ],
    issues: ['ambiguous'], exported: false,
  },
  {
    id: 'd09', orderNo: '322770242001027426', shop: '小莱莎', sales: '胡宁宁', boundAt: '2026-11-20 14:05',
    goodsValue: '1258.50000', freight: '40.00000', line: line(6, 209.75, '007'),
    receipt: { charge: '1258.50000', accountingDate: '2026-11-20 10:27:31' },
    ticket: { waybill: '9402037260', logistics: 'delivered', pickedAt: '2026-11-20 18:55', kind: 'exact', amount: 1258.50,
      invoices: [{ no: 'SHT261121', total: 1258.50, product: 1206.50, fees: 52.00 }] },
    issues: ['unit'], exported: false,
  },
  {
    id: 'd10', orderNo: '322967514001029078', shop: '大莱莎', sales: '田雯', boundAt: '2026-11-21 09:50',
    goodsValue: '112.62000', freight: '40.00000', line: line(2, 56.31),
    receipt: { charge: '112.62000', accountingDate: '2026-11-21 08:12:00' },
    ticket: { waybill: '9494863346', logistics: 'transit', pickedAt: '2026-11-21 17:20', kind: 'exact', amount: 112.62,
      invoices: [{ no: 'SHT261140', total: 112.62, product: 68.32, fees: 44.30 }] },
    issues: ['suspected'], exported: false, occurrence: 1,
  },
  {
    id: 'd11', orderNo: '320588763001021455', shop: '大莱莎', sales: '田雯', boundAt: '2026-11-19 16:20',
    goodsValue: '2038.80000', freight: '50.00000', line: line(12, 169.9),
    receipt: { charge: '2038.80000', accountingDate: '2026-11-19 11:22:47' },
    ticket: { waybill: '9402029276', logistics: 'delivered', pickedAt: '2026-11-19 18:40', kind: 'exact', amount: 2038.80,
      invoices: [{ no: 'SHT261128', total: 2038.80, product: 1980.80, fees: 58.00 }] },
    issues: [], exported: true, exportedAt: '2026-11-20 17:05',
  },
  {
    id: 'd12', orderNo: '321980038001021446', shop: '小莱莎', sales: '李娜', boundAt: '2026-11-22 10:02',
    goodsValue: '450.82000', freight: '45.00000', line: line(2, 225.41),
    receipt: { charge: '450.82000', accountingDate: '2026-11-22 09:00:15' },
    ticket: { waybill: '7006512601', logistics: 'not_picked', pickedAt: null, kind: 'exact', amount: 450.82,
      invoices: [{ no: 'SHT261160', total: 450.82, product: 395.88, fees: 54.94, cancelled: true }] },
    issues: ['invoice_cancelled', 'not_picked'], exported: false,
  },
  {
    id: 'd13', orderNo: '323086342001026452', shop: '新莱莎', sales: '王磊', boundAt: '2026-11-23 08:45',
    goodsValue: '489.00000', freight: '45.00000', line: line(2, 244.5),
    receipt: { charge: '489.00000', accountingDate: '2026-11-22 20:11:02' },
    ticket: { waybill: '9402041180', logistics: 'not_picked', pickedAt: null, kind: 'exact', amount: 489.00,
      invoices: [{ no: 'SHT261185', total: 489.00, product: 444.00, fees: 45.00 }] },
    issues: [], released: { action: '确认已发', by: '张敏', at: '2026-11-23 11:50', reason: 'DHL 已上门取件，系统未更新' }, exported: false,
  },
  {
    id: 'd14', orderNo: '300228362501028534', shop: '小莱莎', sales: '刘洋', boundAt: null,
    goodsValue: '3800.00000', freight: '60.00000', line: line(40, 95),
    receipt: { charge: '3800.00000', accountingDate: '2026-11-22 16:40:51' },
    ticket: null, invoiceNoWaybill: 'SHT261178',
    issues: ['no_waybill'], exported: false,
  },
]

export const orphanReceipts = [
  { orderNo: '322101130501022818', charge: '441.68000', accountingDate: '2026-11-23 10:58:30' },
]

export const audit = {
  d13: [
    { at: '2026-11-23 09:43', who: '张敏', text: '导入订单文件，新增本条申报' },
    { at: '2026-11-23 11:41', who: '张敏', text: '导入收款单，配上收款 489.00' },
    { at: '2026-11-23 11:50', who: '张敏', text: '确认已发：DHL 已上门取件，系统未更新' },
  ],
}
