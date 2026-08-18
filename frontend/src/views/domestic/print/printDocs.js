/**
 * 内贸打印文档构建器 —— 产出**完整独立 HTML 文档**（自带样式），塞进 iframe。
 *
 * 为什么是 iframe 而不是页面里的一块 DOM：
 * 弹框预览要留在订单页上（不能跳走），但 window.print() 打的是整个文档，
 * 页面里的一块 DOM 会连侧边栏和订单列表一起打出来。iframe 自成一个文档，
 * 对它调用 print() 就只打它——预览看到的和打印出来的是同一份东西。
 *
 * 屏幕态（放大预览）和打印态（实际尺寸）用 @media 分开，同一份文档两种呈现。
 */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

// 备注/发型要求是用户自由输入，直接拼进 HTML 会破坏文档结构
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ESCAPES[c])
}

function img(src, cls, alt = '') {
  return src ? `<img class="${cls}" src="${esc(src)}" alt="${esc(alt)}">` : ''
}

function wrapDoc(title, css, body) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>${esc(title)}</title><style>${css}</style></head><body>${body}</body></html>`
}

// ── 二维码标签 30×20mm ────────────────────────────────

const LABEL_CSS = `
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif}
.label{
  width:30mm;height:20mm;padding:1mm;background:#fff;
  display:flex;align-items:center;gap:.8mm;
}
/* 左 LOGO 只取孔雀图形块（横向比例 1.18），高度居中留白 */
.label-logo{height:100%;width:11mm;object-fit:contain;flex-shrink:0}
/* 右二维码吃满剩余宽度：30 − 左右各 1 内边距 − LOGO 11 − 间距 .8 = 16.2
   pixelated 让缩放时码点边缘不被平滑掉 */
.label-qr{height:100%;width:16.2mm;object-fit:contain;flex-shrink:0;image-rendering:pixelated}
.label-qr--text{
  font-size:1.4mm;line-height:1.2;word-break:break-all;
  border:.2mm dashed #666;display:flex;align-items:center;padding:.5mm
}

@media screen{
  body{background:#eceff1;display:flex;flex-direction:column;align-items:center;gap:16px;padding:24px 0}
  /* 30×20mm 在屏幕上只有指甲盖大，放大 3 倍看清楚；打印态不受影响 */
  .label{transform:scale(3);transform-origin:top center;margin-bottom:44mm;box-shadow:0 0 0 .3mm #cfd8dc}
}

@media print{
  @page{size:30mm 20mm;margin:0}
  body{background:#fff;padding:0}
  .label{transform:none;margin:0;box-shadow:none;page-break-after:always}
  .label:last-child{page-break-after:auto}
}`

export function buildLabelDoc({ card, logoUrl, copies = 1 }) {
  const qr = card.qr_code_base64
    ? `<img class="label-qr" src="${esc(card.qr_code_base64)}" alt="报工二维码">`
    : `<div class="label-qr label-qr--text">${esc(card.qr_data)}</div>`
  const one = `<div class="label">${img(logoUrl, 'label-logo', '莱莎健康假发')}${qr}</div>`
  return wrapDoc(`二维码标签 ${card.domestic_no}`, LABEL_CSS, one.repeat(Math.max(1, copies)))
}

// 逐件标签：每个数量一张不同二维码，A1-01/A1-02/... 印在标签上便于人工核对。
export function buildUnitLabelDoc({ data, logoUrl }) {
  const units = data.units || []
  const body = units.map(unit => `<div class="label unit-label">
    <div class="unit-meta">
      ${img(logoUrl, 'unit-logo', '莱莎健康假发')}
      <strong class="unit-code">${esc(unit.unit_code)}</strong>
      <span class="unit-order">${esc(data.domestic_no)}</span>
    </div>
    ${img(unit.qr_image, 'unit-qr', `单件 ${unit.unit_code}`)}
  </div>`).join('')
  const css = `${LABEL_CSS}
    .unit-label{gap:.6mm}
    .unit-meta{width:10.6mm;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0}
    .unit-logo{width:9.5mm;height:8mm;object-fit:contain}
    .unit-code{font-size:2.4mm;line-height:1.15;white-space:nowrap}
    .unit-order{max-width:10.2mm;font-size:1.25mm;line-height:1.15;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    .unit-qr{width:16.8mm;height:16.8mm;object-fit:contain;image-rendering:pixelated;flex-shrink:0}
  `
  return wrapDoc(`逐件二维码 ${data.domestic_no}`, css, body)
}

// 订单进度小程序码标签：同一版式（左 LOGO 右码），码换成微信小程序码
export function buildWxacodeLabelDoc({ image, domesticNo, logoUrl, copies = 1 }) {
  const one = `<div class="label">${img(logoUrl, 'label-logo', '莱莎健康假发')}${img(image, 'label-qr', '订单进度码')}</div>`
  return wrapDoc(`进度码标签 ${domesticNo}`, LABEL_CSS, one.repeat(Math.max(1, copies)))
}

// ── 工艺流转卡 A4 ─────────────────────────────────────

const CARD_CSS = `
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#000}
.card{width:210mm;min-height:148mm;padding:12mm;background:#fff}
.header{display:flex;justify-content:space-between;align-items:flex-start;
  border-bottom:2px solid #000;padding-bottom:8px}
.header h1{margin:0;font-size:22px}
.order-no{margin-top:4px;font-size:13px}
.special-badge{padding:4px 12px;border:2px solid #000;font-weight:700}
.body-row{display:flex;gap:16px;margin-top:10px}
.left{flex:1}
.info-table{width:100%;border-collapse:collapse;font-size:14px}
.info-table td{border:1px solid #333;padding:6px 8px}
.info-table td:first-child{width:90px;background:#f0f0f0}
.qty-value{font-size:20px;font-weight:700}
.qr-section{width:130px;text-align:center}
.qr-section img{width:120px;height:120px;image-rendering:pixelated}
.qr-text{font-size:11px;word-break:break-all;border:1px dashed #666;padding:6px}
.qr-hint{font-size:11px;margin-top:4px}
.req-section{margin-top:10px;border:1px solid #333;padding:6px 8px}
.req-label{font-weight:700;font-size:13px;margin-bottom:4px}
.req-text{font-size:13px;white-space:pre-wrap;margin-bottom:6px}
.req-imgs{display:flex;flex-wrap:wrap;gap:4mm}
.req-imgs img{width:28mm;height:28mm;object-fit:cover;border:1px solid #999}
.process-section{margin-top:12px}
.process-section h3{font-size:14px;margin:0 0 6px}
.process-table{width:100%;border-collapse:collapse;font-size:13px}
.process-table th,.process-table td{border:1px solid #333;padding:6px 8px;text-align:left}
.process-table th{background:#f0f0f0}
.sign-cell{height:28px}
.footer{display:flex;justify-content:space-between;margin-top:12px;padding-top:6px;
  border-top:1px solid #999;font-size:11px;color:#555}

@media screen{
  body{background:#eceff1;padding:20px 0}
  .card{margin:0 auto;box-shadow:0 2px 12px rgba(0,0,0,.15)}
}

@media print{
  /* 卡片本身就是 A4 满宽，页边距归零由卡片自己的 12mm 内边距承担 */
  @page{size:A4;margin:0}
  body{background:#fff;padding:0}
  .card{margin:0;box-shadow:none}
}`

const SECTIONS = [
  ['hairstyle', 'hairstyle_images', '发型'],
  ['color', 'color_images', '颜色'],
  ['style_requirement', 'style_images', '发型要求'],
  ['remark', 'remark_images', '备注'],
]

export function buildCardDoc({ card, imageMap = {} }) {
  const item = card.item || {}

  const reqBlocks = SECTIONS.map(([textKey, imgKey, label]) => {
    const text = item[textKey]
    const paths = item[imgKey] || []
    if (!text && !paths.length) return ''
    const pics = paths.map(p => img(imageMap[p], '', label)).join('')
    return `<div class="req-section">
      <div class="req-label">${esc(label)}</div>
      ${text ? `<div class="req-text">${esc(text)}</div>` : ''}
      ${pics ? `<div class="req-imgs">${pics}</div>` : ''}
    </div>`
  }).join('')

  const steps = (item.steps || []).map(s => `<tr>
      <td>${esc(s.step_order)}</td><td>${esc(s.process_name)}</td>
      <td>${esc(s.completed_qty)} / ${esc(item.order_qty)}</td>
      <td class="sign-cell"></td><td class="sign-cell"></td>
    </tr>`).join('')

  const qr = card.qr_code_base64
    ? `<img src="${esc(card.qr_code_base64)}" alt="报工二维码">`
    : `<div class="qr-text">${esc(card.qr_data)}</div>`

  const body = `<div class="card">
  <div class="header">
    <div>
      <h1>内贸流转卡</h1>
      <div class="order-no">${esc(card.domestic_no)} · 客户订单号 ${esc(card.order_no)}</div>
    </div>
    ${card.order_type_label === '特单' ? '<div class="special-badge">特单</div>' : ''}
  </div>

  <div class="body-row">
    <div class="left">
      <table class="info-table">
        <tr><td>客户店名</td><td><strong>${esc(card.customer_name)}</strong></td></tr>
        <tr><td>产品</td><td><strong>${esc(item.product_name)}</strong></td></tr>
        <tr><td>生产数量</td><td><span class="qty-value">${esc(item.order_qty)}</span> 件</td></tr>
        <tr><td>下单日期</td><td>${esc(card.order_date)}</td></tr>
      </table>
    </div>
    <div class="qr-section">${qr}<div class="qr-hint">扫码报工<br>可按数量拆批</div></div>
  </div>

  ${reqBlocks}

  ${steps ? `<div class="process-section">
    <h3>工序流转（每道做完扫码报工，可只报部分数量）</h3>
    <table class="process-table">
      <thead><tr><th>#</th><th>工序</th><th>已完成</th><th>本次数量</th><th>经手人</th></tr></thead>
      <tbody>${steps}</tbody>
    </table>
  </div>` : ''}

  <div class="footer">
    <span>莱莎方舟平台 · 内贸生产</span>
    <span>打印时间：${esc(card.printed_at)}</span>
    <span>卡号：${esc(card.qr_data)}</span>
  </div>
</div>`

  return wrapDoc(`流转卡 ${card.domestic_no}`, CARD_CSS, body)
}
