import test from 'node:test'
import assert from 'node:assert/strict'
import { buildInspectionDoc, buildOutboundDoc } from '../src/views/shipping/print/printDocs.js'

const outboundPayload = {
  record: {
    outbound_record_id: 7,
    outbound_no: 'CK20260901-001',
    outbound_date: '2026-09-01',
    customer_name: '王女士<旗舰店>',
    owner_name: '张三',
  },
  items: [
    { item_id: 1, product_name: '真人发头套', spec: '自然色 16寸', sku: 'TT-16', qty: 2, unit: '件' },
    { item_id: 2, product_name: '发片', spec: '深棕', sku: 'FP-DB', qty: 5, unit: '片' },
  ],
  qr_code_base64: 'data:image/png;base64,aGVsbG8=',
}

test('出库单文档：A4 自含样式 + 单头字段 + 明细表 + 二维码补 data: 前缀', () => {
  const doc = buildOutboundDoc(outboundPayload)

  assert.match(doc, /^<!doctype html>/)
  assert.match(doc, /@page\{size:A4;margin:0\}/)
  assert.match(doc, /@media print/)
  assert.match(doc, /<h1>出库单<\/h1>/)
  assert.match(doc, /CK20260901-001/)
  // 自由输入字段必须转义，不能原样进 HTML
  assert.match(doc, /王女士&lt;旗舰店&gt;/)
  assert.ok(!doc.includes('王女士<旗舰店>'))
  assert.match(doc, /真人发头套/)
  assert.match(doc, /FP-DB/)
  // 后端给纯 base64，进 <img> 必须带 data URL 头
  assert.match(doc, /src="data:image\/png;base64,aGVsbG8="/)
})

test('出库单文档：无二维码时不输出破损 img', () => {
  const doc = buildOutboundDoc({ ...outboundPayload, qr_code_base64: '' })

  assert.ok(!doc.includes('<div class="qr-section">'))
  assert.ok(!doc.includes('data:image/png;base64'))
})

test('验货单文档：整单照片在前，明细照片按组标注产品名称', () => {
  const doc = buildInspectionDoc({
    record: {
      outbound_no: 'CK20260901-001',
      customer_name: '王女士',
      submitted_by_name: '李四',
      submitted_at: '2026-09-01 10:30:00',
      remark: '包装完好',
    },
    items: outboundPayload.items,
    photoItemMap: { 1: '真人发头套', 2: '发片' },
    photosDataUrls: [
      { item_id: 2, dataUrl: 'data:image/jpeg;base64,cGljMg==' },
      { item_id: null, dataUrl: 'data:image/jpeg;base64,cGljMA==' },
      { item_id: 1, dataUrl: 'data:image/jpeg;base64,cGljMQ==' },
      // 不属于任何明细的照片按整单照片兜底
      { item_id: 999, dataUrl: 'data:image/jpeg;base64,cGljOTk5' },
    ],
  })

  assert.match(doc, /<h1>发货验货单<\/h1>/)
  assert.match(doc, /出库单号：CK20260901-001/)
  assert.match(doc, /李四/)
  assert.match(doc, /包装完好/)

  const wholeIdx = doc.indexOf('整单照片')
  const item1Idx = doc.indexOf('cGljMQ==')
  const item2Idx = doc.indexOf('cGljMg==')
  const fallbackIdx = doc.indexOf('cGljOTk5')
  assert.ok(wholeIdx > -1, '整单照片分组存在')
  // 整单（含兜底）照片排在明细照片之前
  assert.ok(wholeIdx < item1Idx && wholeIdx < item2Idx)
  assert.ok(fallbackIdx > -1 && fallbackIdx < item1Idx && fallbackIdx < item2Idx)
  // 明细分组标题带产品名称
  assert.match(doc, /<div class="photo-group-title">真人发头套<\/div>/)
  assert.match(doc, /<div class="photo-group-title">发片<\/div>/)
  assert.match(doc, /@page\{size:A4;margin:0\}/)
})

test('验货单文档：无照片无备注时不输出空区块', () => {
  const doc = buildInspectionDoc({
    record: { outbound_no: 'CK1', customer_name: '客', submitted_by_name: '人', submitted_at: '', remark: '' },
    items: [],
    photosDataUrls: [],
    photoItemMap: {},
  })

  assert.ok(!doc.includes('<div class="photo-section">'))
  assert.ok(!doc.includes('<div class="remark-section">'))
  assert.ok(!doc.includes('<div class="items-section">'))
})
