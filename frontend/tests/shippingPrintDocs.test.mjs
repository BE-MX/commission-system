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
    remark: '分箱包装\n附标签 <script>alert("x")</script>',
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
  // 客户名称只保留前三个字符，其他自由输入字段仍需转义
  assert.match(doc, /王女士\*\*\*/)
  assert.ok(!doc.includes('王女士<旗舰店>'))
  assert.match(doc, /真人发头套/)
  assert.ok(!doc.includes('<th>SKU</th>'))
  assert.ok(!doc.includes('FP-DB'))
  assert.ok(!doc.includes('TT-16'))
  assert.match(doc, /发货备注/)
  assert.match(doc, /分箱包装\n附标签 &lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/)
  assert.ok(!doc.includes('<script>'))
  // 后端给纯 base64，进 <img> 必须带 data URL 头
  assert.match(doc, /src="data:image\/png;base64,aGVsbG8="/)
})

test('出库单文档：空备注明确显示无', () => {
  const doc = buildOutboundDoc({ ...outboundPayload, record: { ...outboundPayload.record, remark: null } })
  assert.match(doc, /<div class="remark-content">无<\/div>/)
})

test('出库单拆分首个斜杠，保留复合颜色、规格并为批次号留空', () => {
  const doc = buildOutboundDoc({
    ...outboundPayload,
    items: [{ product_name: 'Super Double Drawn Genius Weft/22/#8TP18/60/20g', spec: 'B1天才发帘', qty: 4, unit: '件' }],
  })
  assert.match(doc, /<td class="product-category">Super Double Drawn Genius Weft<\/td>/)
  assert.match(doc, /<td class="product-details">22\/<wbr>#8TP18\/<wbr>60\/<wbr>20g<\/td>/)
  assert.match(doc, /<td class="product-spec"><strong class="spec-grade">B1<\/strong>天才发帘<\/td>\s*<td class="product-details">/)
  assert.match(doc, /<th>产品类别<\/th><th>规格<\/th><th>颜色\/尺寸\/克重<\/th>/)
  assert.match(doc, /<th>批次号<\/th>/)
  assert.match(doc, /<td class="batch-no"><\/td>/)
  assert.ok(!doc.includes('<th>单位</th>'))
  assert.ok(!doc.includes('<td>件</td>'))
})

test('出库单名称缺失、无分隔符、全角分隔符及特殊字符不丢失或注入 HTML', () => {
  const doc = buildOutboundDoc({
    ...outboundPayload,
    items: [
      { product_name: null },
      { product_name: '真人发头套' },
      { product_name: ' Tape & Weft ／ <img src=x>/20g ' },
    ],
  })
  assert.match(doc, /<td class="product-category"><\/td>/)
  assert.match(doc, /<td class="product-category">真人发头套<\/td>\s*<td class="product-spec"><\/td>\s*<td class="product-details"><\/td>/)
  assert.match(doc, /<td class="product-category">Tape &amp; Weft<\/td>/)
  assert.match(doc, /<td class="product-details">&lt;img src=x&gt;\/<wbr>20g<\/td>/)
  assert.ok(!doc.includes('<img src=x>'))
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
  assert.match(doc, /<th>SKU<\/th>/)
  assert.match(doc, /FP-DB/)

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


test('规格仅突出 B1/B3，保留普通文字并安全转义', () => {
  const doc = buildOutboundDoc({ ...outboundPayload, items: [
    { spec: 'B1天才 / B3平行 / B10 / AB1 / <script>' },
  ] })
  assert.match(doc, /<strong class="spec-grade">B1<\/strong>天才/)
  assert.match(doc, /<strong class="spec-grade">B3<\/strong>平行/)
  assert.equal((doc.match(/<strong class="spec-grade">/g) || []).length, 2)
  assert.match(doc, /B10 \/ AB1 \/ &lt;script&gt;/)
  assert.match(doc, /spec-grade\{font-size:16px;font-weight:700\}/)
})


test('outbound masks customer names only in the rendered document', () => {
  for (const [name, expected] of [
    ['Inessa Wassiljev/Haarverlängerung', 'Ine***'], ['AB', 'AB***'],
    ['ABC', 'ABC***'], ['王女士旗舰店', '王女士***'],
    ['😀AB Customer', '😀AB***'], [' <&>Company ', '&lt;&amp;&gt;***'],
    [null, ''], ['', ''], ['   ', ''],
  ]) {
    const record = { ...outboundPayload.record, customer_name: name }
    const doc = buildOutboundDoc({ ...outboundPayload, record })
    assert.ok(doc.includes(`<strong>${expected}</strong>`))
    assert.equal(record.customer_name, name)
  }
})
