// Fictional fixtures. Money uses integer cents; four-decimal unit prices use strings.
const baseOrder = {
  number: 'LS-PI-20261008-016', type: '预售单', customer: 'Kari Alford', company: 'Alford Hair Studio',
  grade: 'A', sales: 'Derek', merchandiser: 'Lily', date: '2026-10-08', orderId: '26385',
  contact: 'Kari Alford', email: 'kari@example.com', phone: '+1 (202) 555-0148',
  address: '18 West Avenue, New York, NY 10001, United States', express: 'DHL',
  paymentTerm: '分批付款，分批出库', method: 'Bank Transfer', sync: '已同步',
  product: 180000, packaging: 4000, shipping: 0, surcharge: 0, total: 184000,
  effective: 110400, pending: 36800, freightTotal: 12000, freightEffective: 8000, freightPending: 4000,
  shipped: 12, reserved: 8, unknown: false, restricted: false, batchAvailable: 24533,
  remark: '分批交付；发货前核对色号与长度。每批运费单独结算。',
  items: [
    { id: 1, name: 'Genius Weft · Premium', spec: '18″ / #4 / Straight / 50g', quantity: 12, unitPrice: '75.0000', lineAmount: 90000, discount: 0, shipped: 6 },
    { id: 2, name: 'Genius Weft · Premium', spec: '20″ / #8 / Straight / 50g', quantity: 8, unitPrice: '75.0000', lineAmount: 60000, discount: 0, shipped: 4 },
    { id: 3, name: 'Genius Weft · Premium', spec: '22″ / #60 / Straight / 50g', quantity: 4, unitPrice: '75.0000', lineAmount: 30000, discount: 0, shipped: 2 },
  ],
  outbounds: [
    { id: 'o1', number: 'CK20261008-0016', batch: '第 1 批', settlement: 'LS-PI-20261008-016-S01', date: '2026-10-08', quantity: 12, state: '已出库', tone: 'success', inspection: '已提交', maker: 'Lily', quantities: [6, 4, 2], actual: true, detail: '出库事实已核验；本批 12 件计入订单出库进度。', freight: 8000 },
    { id: 'o2', number: null, batch: '第 2 批', settlement: 'LS-PI-20261008-016-S02', date: null, quantity: 8, state: '等待款项齐备', tone: 'warning', inspection: '尚未生成', maker: 'Lily', quantities: [4, 2, 2], actual: false, detail: '本批已登记部分回款，款项尚未齐备；8 件尚未生成出库单，不计入已出库数量。', freight: 4000 },
  ],
  receipts: [
    { id: 'r1', number: 'HK20261006-0016', remote: 'HK-OKKI-26385-01', purpose: '预付款', target: '订单商品款', date: '2026-10-06', amount: 18400, fee: 0, source: '自动生成', sync: '已同步', finance: '已生效', effective: true, proof: '首款银行回单.png', batch: null, note: '首笔预付款；方舟在最后一批结算时抵扣，抵扣不重复计算回款。' },
    { id: 'r2', number: 'HK20261007-0021', remote: 'HK-OKKI-26385-02', purpose: '批次商品款', target: '第 1 批', date: '2026-10-07', amount: 92000, fee: 0, source: '批量登记', sync: '已同步', finance: '已生效', effective: true, proof: '第一批银行回单.png', batch: 'RB20261007-0008', note: '第 1 批商品净额 USD 900.00，包装费 USD 20.00；非末批不抵扣预付款，本笔商品款 USD 920.00。' },
    { id: 'r3', number: 'HK20261007-0022', remote: 'HK-OKKI-F26385-01', purpose: '运费', target: '第 1 批运费单', date: '2026-10-07', amount: 8000, fee: 0, source: '批量登记', sync: '已同步', finance: '已生效', effective: true, proof: '第一批银行回单.png', batch: 'RB20261007-0008', note: '独立运费应收；不占用订单商品款登记额度。' },
    { id: 'r4', number: 'HK20261008-0036', remote: 'HK-OKKI-26385-03', purpose: '批次商品款', target: '第 2 批', date: '2026-10-08', amount: 36800, fee: 0, source: '批量登记', sync: '已同步', finance: '未生效', effective: false, proof: '第二批银行回单.png', batch: 'RB20261008-0012', note: '已同步至小满，财务尚未生效；占用登记额度，不计入已生效回款。' },
    { id: 'r5', number: 'HK20261008-0037', remote: 'HK-OKKI-F26385-02', purpose: '运费', target: '第 2 批运费单', date: '2026-10-08', amount: 4000, fee: 0, source: '批量登记', sync: '已同步', finance: '未生效', effective: false, proof: '第二批银行回单.png', batch: 'RB20261008-0012', note: '第 2 批运费款待财务生效；独立于商品款统计。' },
  ],
};
const cloneOrder = () => JSON.parse(JSON.stringify(baseOrder));
const scenarios = {
  partial: cloneOrder(),
  complete: (() => { const o = cloneOrder(); Object.assign(o, {number:'LS-PI-20261008-015', type:'库存单', company:'Mason Hair Co.', customer:'Olivia Mason', total:220500, product:216000, packaging:2500, shipping:2000, effective:220500, pending:0, freightTotal:0, freightEffective:0, freightPending:0, shipped:24, reserved:0, paymentTerm:'款到发货', orderId:'26384', remark:'所有商品随本次出库交付。'}); o.items.forEach(i => {i.unitPrice='90.0000';i.lineAmount=i.quantity*9000;i.shipped=i.quantity;});o.contact='Olivia Mason';o.email='olivia@example.com';o.batchAvailable=null; o.outbounds=[{...o.outbounds[0], number:'CK20261008-0015',quantity:24,quantities:[12,8,4],settlement:null,batch:'整单出库',detail:'出库事实已核验，24 件全部出库。',freight:0}];o.receipts=[{...o.receipts[0],number:'HK20261008-0015',date:'2026-10-08',amount:220500,purpose:'订单回款',remote:'HK-OKKI-26384-01',proof:'整单银行回单.png',note:'整单回款已生效。'}];return o; })(),
  generated: (() => { const o=cloneOrder();Object.assign(o,{number:'LS-PI-20261008-018',type:'库存单',orderId:'26386',effective:184000,pending:0,freightTotal:0,freightEffective:0,freightPending:0,shipped:0,reserved:24,batchAvailable:null,paymentTerm:'款到发货',remark:'出库单已生成，等待仓库实际出库。'});o.items.forEach(i=>i.shipped=0);o.outbounds=[{...o.outbounds[0],number:'CK20261008-0018',date:null,batch:'整单出库',settlement:null,quantity:24,quantities:[12,8,4],state:'已生成',tone:'info',inspection:'未检验',freight:0,detail:'出库单已生成，但尚未确认实际出库；24 件不计入已出库进度。'}];o.receipts=[{...o.receipts[0],number:'HK20261008-0018',remote:'HK-OKKI-26386-01',date:'2026-10-08',amount:184000,purpose:'订单回款',note:'订单回款已生效，等待实际出库。'}];return o; })(),
  draft: (() => {const o=cloneOrder();Object.assign(o,{number:'LS-PI-20261008-017',type:'生产单',company:'Nova Hair Boutique',customer:'Emma Wilson',sync:'未同步',orderId:null,total:200000,product:196000,packaging:4000,shipping:0,effective:0,pending:0,shipped:0,reserved:0,freightTotal:0,freightEffective:0,freightPending:0,paymentTerm:'定制订单，确认后生产',remark:'等待客户确认色号和长度。'});o.items=[{...o.items[0],name:'Custom Weft · Premium',quantity:20,unitPrice:'98.9975',discount:-1995,lineAmount:196000,shipped:0}];o.contact='Emma Wilson';o.email='emma@example.com';o.batchAvailable=null;o.outbounds=[];o.receipts=[];return o;})(),
  exception: (() => {const o=cloneOrder();o.unknown=true;o.receipts[3].sync='待核对';o.receipts[3].finance='未核验';return o;})(),
  order_failed: (() => {const o=cloneOrder();o.sync='同步失败';return o;})(),
  outbound_issue: (() => {const o=cloneOrder();o.unknown=true;o.outbounds[0].state='待核对';o.outbounds[0].tone='warning';o.outbounds[0].detail='出库结果待核对，请核实原单。';return o;})(),
  receipt_failed: (() => {const o=cloneOrder();o.receipts[3].sync='同步失败';o.receipts[3].remote=null;o.receipts[3].finance='未核验';o.receipts[3].note='回款同步失败，请核对原单并重试；该笔款项仍占用登记额度。';return o;})(),
  exception_all: (() => {const o=cloneOrder();o.sync='同步失败';o.unknown=true;o.outbounds[0].state='待核对';o.outbounds[0].tone='warning';o.receipts[3].sync='同步失败';o.receipts[3].remote=null;o.receipts[3].finance='未核验';o.receipts[3].note='回款同步失败，请核对原单并重试；该笔款项仍占用登记额度。';return o;})(),
  restricted: (() => {const o=cloneOrder();o.restricted=true;return o;})(),
};
