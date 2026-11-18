// 原型示例数据。行内容取自样本单据 7085384 的版式，订单与候选为示意，不代表真实库存。
// 订单候选只显示「类型 + 提取出的编号 + 日期」：发票号原文常带客户名，仓库人员无权查看（需求 11.1）。

export const drafts = [
  { id: 'd1', inbound: 'FI20261118-003', delivery: '7085384', date: '11-11', state: 'review', label: '待核对 · 4 行待选择' },
  { id: 'd2', inbound: 'FI20261118-002', delivery: '7085398', date: '11-15', state: 'recognizing', label: '识别中' },
  { id: 'd3', inbound: 'FI20261117-006', delivery: '7085389', date: '11-12', state: 'partial', label: '已入库 6 行 · 2 行待补录' },
]

// status: matched 绿 / choose 黄（选产品或确认换算）/ decide 黄（选订单或处理方式）/ blocked 红 / skipped 灰
// target: { kind: 'po' | 'invoice' | 'cross' | 'none', label, open }  open = 可分配 / 可对应余量
export function reviewGroups() {
  return [
    {
      id: 'g983', title: '生产备货订单 · 编号 983', sub: '2026-09-30 · 单单分配 · 回写已入库数量', tag: ['tag-success', '已对应'],
      lines: [
        { id: 'l1', raw: '983单  PU  22"  4#  20g  90条', qty: 90, unit: '条', status: 'matched',
          spec: 'Standard Double Drawn Genius Weft / 22" / #4 / 20g',
          target: { kind: 'po', label: '备货单 983', open: 90 },
          edit: { ref: '983', grade: '', length: '22', color: '4#', weight: '20', quantity: 90 } },
        { id: 'l2', raw: '—  —  —  P2-8  —  180条', qty: 180, unit: '条', status: 'choose',
          spec: 'Genius Weft / 22" / #P2/8 / 20g', why: '两个等级都有这个规格，请选择',
          inherited: '单号、工艺、长度、克重继承上一行',
          target: { kind: 'po', label: '备货单 983' },
          edit: { ref: '983', grade: '', length: '22', color: 'P2-8', weight: '20', quantity: 180 },
          candidates: [
            { id: 'c1', name: 'Super Double Drawn Genius Weft / 22" / #P2/8 / 20g', order: 180, open: 180, qtyMatch: true },
            { id: 'c2', name: 'Standard Double Drawn Genius Weft / 22" / #P2/8 / 20g', order: 120, open: 120 },
          ] },
        { id: 'l3', raw: '—  —  16"  P2-8  —  60条', qty: 60, unit: '条', status: 'matched',
          spec: 'Super Double Drawn Genius Weft / 16" / #P2/8 / 20g',
          target: { kind: 'po', label: '备货单 983', open: 60 },
          edit: { ref: '983', grade: '', length: '16', color: 'P2-8', weight: '20', quantity: 60 } },
        { id: 'l4', raw: '—  —  22"  P4-18  —  90条', qty: 90, unit: '条', status: 'choose',
          spec: 'Genius Weft / 22" / #P4/18 / 20g', why: '两个等级都有这个规格，请选择',
          target: { kind: 'po', label: '备货单 983' },
          edit: { ref: '983', grade: '', length: '22', color: 'P4-18', weight: '20', quantity: 90 },
          candidates: [
            { id: 'c3', name: 'Super Double Drawn Genius Weft / 22" / #P4/18 / 20g', order: 90, open: 90, qtyMatch: true },
            { id: 'c4', name: 'Standard Double Drawn Genius Weft / 22" / #P4/18 / 20g', order: 150, open: 150 },
          ] },
        { id: 'l5', raw: '—  贴片  —  8#  2.5g  500片', qty: 500, unit: '片', status: 'choose',
          spec: 'Tape Hair / 22" / #8 / 2.5g', why: '两个等级的下单数都是 500，请按实物选择',
          target: { kind: 'po', label: '备货单 983' },
          edit: { ref: '983', grade: '', length: '22', color: '8#', weight: '2.5', quantity: 500 },
          candidates: [
            { id: 'c5', name: 'Super Double Drawn Tape Hair / 22" / #8 / 2.5g', order: 500, open: 500, qtyMatch: true },
            { id: 'c6', name: 'Standard Double Drawn Tape Hair / 22" / #8 / 2.5g', order: 500, open: 500, qtyMatch: true },
          ] },
      ],
    },
    {
      id: 'g1009', title: '订单发票生产单 · 编号 1009', sub: '2026-10-09 · 只记录对应，不改发票', tag: ['tag-info', '发票对应'],
      lines: [
        { id: 'l6', raw: '1009单  —  24"  5A9A-613  20g  120条', qty: 120, unit: '条', status: 'matched',
          spec: 'Super Double Drawn Genius Weft / 24" / #5ATP9A/613 / 20g', rule: '颜色别名表：5A9A-613 → #5ATP9A/613',
          target: { kind: 'invoice', label: '发票生产单 1009 第 3 行', open: 120 },
          edit: { ref: '1009', grade: '', length: '24', color: '5A9A-613', weight: '20', quantity: 120 } },
      ],
    },
    {
      id: 'g1054', title: '编号 1054 命中 2 张单', sub: '请选择这批货对应哪张单', tag: ['tag-warning', '待选择'], multi: true,
      lines: [
        { id: 'l7', raw: '1054单  —  —  878-18  5g  40片', qty: 40, unit: '片', status: 'decide',
          spec: 'Tape Hair / 22" / 878-18 / 5g', why: '单号命中 2 张单，请先选订单',
          edit: { ref: '1054', grade: '', length: '22', color: '878-18', weight: '5', quantity: 40 },
          orders: [
            { id: 'o1', name: '订单发票生产单 · 编号 1054', meta: '2026-10-20 · 发票对应' },
            { id: 'o2', name: '订单发票生产单 · 编号 1054', meta: '2026-10-24 · 发票对应' },
          ],
          // 选定订单后，在该发票明细里匹配：两个等级都有
          afterOrder: [
            { id: 'c7', name: 'Super Double Drawn Tape Hair / 22" / #8TP8/18 / 5g', order: 40, open: 40, qtyMatch: true },
            { id: 'c8', name: 'Standard Double Drawn Tape Hair / 22" / #8TP8/18 / 5g', order: 60, open: 60 },
          ] },
      ],
    },
    {
      id: 'g954', title: '编号 954 未找到可对应的订单', sub: '按 SKU 在生产备货订单里跨单分配', tag: ['tag-gold', '跨单分配'],
      lines: [
        { id: 'l8', raw: '954单  PU  22"  878-18  60g  50条', qty: 50, unit: '条', status: 'choose', ruleConfirm: true,
          spec: 'Super Double Drawn Genius Weft / 22" / #8TP8/18 / 60g', why: '按规则换算：878-18 → #8TP8/18，请确认',
          target: { kind: 'cross', label: '跨单：备货单 1071（加急）30 条 + 备货单 942 20 条' },
          edit: { ref: '954', grade: '', length: '22', color: '878-18', weight: '60', quantity: 50 },
          candidates: [
            { id: 'c9', name: 'Super Double Drawn Genius Weft / 22" / #8TP8/18 / 60g', meta: '规则换算的唯一结果' },
          ] },
        { id: 'l9', raw: '1011单  贴片  22"  2B-2B-5A  2.5g  200片', qty: 200, unit: '片', status: 'matched',
          spec: 'Standard Double Drawn Tape Hair / 22" / #2BTP2B/5A / 2.5g', rule: '颜色别名表：2B-2B-5A → #2BTP2B/5A',
          target: { kind: 'none', label: '单号对应库存单，不做对应；无未完成备货单含此 SKU，只入库' },
          edit: { ref: '1011', grade: '', length: '22', color: '2B-2B-5A', weight: '2.5', quantity: 200 } },
      ],
    },
    {
      id: 'g934', title: '无法入库与不入库的行', sub: '本次跳过，处理后可在本单补录', tag: ['tag-danger', '需处理'],
      lines: [
        { id: 'l10', raw: '934单  —  18"  R-I-C  —  4片', qty: 4, unit: '片', status: 'blocked',
          spec: '18" / R-I-C', why: '找不到产品：颜色「R-I-C」在小满没有对应 SKU',
          edit: { ref: '934', grade: '', length: '18', color: 'R-I-C', weight: '', quantity: 4 } },
        { id: 'l11', raw: '1001单  色样', qty: 0, unit: '', status: 'skipped', spec: '色样', why: '色样不入库' },
      ],
    },
  ]
}

export const desktopRows = [
  { inbound: 'FI20261118-003', delivery: '7085384', date: '11-18 10:42', who: '仓库 · 王', lines: 11, qty: 1334, status: ['tag-warning', '待核对'], sync: '—' },
  { inbound: 'FI20261118-002', delivery: '7085398', date: '11-18 10:31', who: '仓库 · 王', lines: 0, qty: 0, status: ['tag-info', '识别中'], sync: '—' },
  { inbound: 'FI20261117-006', delivery: '7085389', date: '11-17 16:05', who: '仓库 · 李', lines: 8, qty: 236, status: ['tag-gold', '部分入库'], sync: '已同步' },
  { inbound: 'FI20261117-004', delivery: '7085387', date: '11-17 11:20', who: '仓库 · 李', lines: 16, qty: 1592, status: ['tag-success', '已完成'], sync: '已同步' },
  { inbound: 'FI20261116-002', delivery: '7085386', date: '11-16 15:47', who: '仓库 · 王', lines: 16, qty: 760, status: ['tag-danger', '结果待核对'], sync: '待核对' },
]
