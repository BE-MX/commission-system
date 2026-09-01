/**
 * 发货检验打印文档构建器 —— 产出**完整独立 HTML 文档**（自带样式），塞进 iframe。
 *
 * 为什么是 iframe 而不是页面里的一块 DOM：弹框预览要留在列表页上（不能跳走），
 * 但 window.print() 打的是整个文档，页面里的一块 DOM 会连侧边栏一起打出来。
 * iframe 自成一个文档，对它调用 print() 就只打它——所见即所印。
 * （同 domestic 打印的约定，见 views/domestic/print/printDocs.js）
 *
 * 屏幕态（放大预览）和打印态（实际尺寸）用 @media 分开，同一份文档两种呈现。
 */

// 用相对路径而非 '@/' 别名：本文件被 node --test 直接 import，别名只在 Vite 下可解析
import { currentBeijingDateTime } from '../../../utils/datetime.js'

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

// 单号/备注/产品名都可能来自自由输入，直接拼进 HTML 会破坏文档结构
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ESCAPES[c])
}

function wrapDoc(title, css, body) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>${esc(title)}</title><style>${css}</style></head><body>${body}</body></html>`
}

// ── A4 单据共用样式（仿 domestic CARD_CSS）────────────────

const SHEET_CSS = `
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#000}
.sheet{width:210mm;min-height:287mm;padding:12mm;background:#fff}
.header{display:flex;justify-content:space-between;align-items:flex-start;
  border-bottom:2px solid #000;padding-bottom:8px}
.header h1{margin:0;font-size:22px}
.doc-no{margin-top:4px;font-size:13px}
.body-row{display:flex;gap:16px;margin-top:10px}
.left{flex:1}
.info-table{width:100%;border-collapse:collapse;font-size:14px}
.info-table td{border:1px solid #333;padding:6px 8px}
.info-table td:first-child{width:90px;background:#f0f0f0}
.qr-section{width:130px;text-align:center}
.qr-section img{width:120px;height:120px;image-rendering:pixelated}
.qr-hint{font-size:11px;margin-top:4px}
.items-section{margin-top:12px}
.items-section h3{font-size:14px;margin:0 0 6px}
.items-table{width:100%;border-collapse:collapse;font-size:13px}
.items-table th,.items-table td{border:1px solid #333;padding:6px 8px;text-align:left}
.items-table th{background:#f0f0f0}
.items-table .num{text-align:right}
.remark-section{margin-top:10px;border:1px solid #333;padding:6px 8px;font-size:13px}
.remark-label{font-weight:700;margin-bottom:4px}
.photo-section{margin-top:12px}
.photo-section h3{font-size:14px;margin:0 0 6px}
.photo-group{margin-bottom:10px}
.photo-group-title{font-size:13px;font-weight:700;margin-bottom:4px}
.photo-grid{display:flex;flex-wrap:wrap;gap:4mm}
.photo-cell{margin:0;width:44mm}
.photo-cell img{width:44mm;height:44mm;object-fit:cover;border:1px solid #999}
.photo-cell figcaption{font-size:11px;color:#333;margin-top:2px;text-align:center;
  overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.footer{display:flex;justify-content:space-between;margin-top:12px;padding-top:6px;
  border-top:1px solid #999;font-size:11px;color:#555}

@media screen{
  body{background:#eceff1;padding:20px 0}
  .sheet{margin:0 auto;box-shadow:0 2px 12px rgba(0,0,0,.15)}
}

@media print{
  /* 单据本身就是 A4 满宽，页边距归零由单据自己的 12mm 内边距承担 */
  @page{size:A4;margin:0}
  body{background:#fff;padding:0}
  .sheet{margin:0;box-shadow:none}
}`

function printedAt() {
  // 打印时间统一走北京时间工具（宪法 23），不直接用 new Date().toLocaleString
  return currentBeijingDateTime()
}

function itemsTable(items) {
  const rows = (items || []).map((item, index) => `<tr>
      <td>${index + 1}</td>
      <td>${esc(item.product_name)}</td>
      <td>${esc(item.spec)}</td>
      <td>${esc(item.sku)}</td>
      <td class="num">${esc(item.qty)}</td>
      <td>${esc(item.unit)}</td>
    </tr>`).join('')
  if (!rows) return ''
  return `<div class="items-section">
    <h3>出库明细</h3>
    <table class="items-table">
      <thead><tr><th>#</th><th>产品名称</th><th>规格</th><th>SKU</th><th>数量</th><th>单位</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`
}

// ── 出库单 A4 ─────────────────────────────────────────

export function buildOutboundDoc({ record, items = [], qr_code_base64 = '' }) {
  // 后端 _qr_png_base64 返回的已是完整 data URL（含 data:image/png;base64, 前缀），直接进 <img>
  const qr = qr_code_base64
    ? `<img src="${esc(qr_code_base64)}" alt="出库单二维码">`
    : ''
  const qrSection = qr
    ? `<div class="qr-section">${qr}<div class="qr-hint">扫码查看出库信息</div></div>`
    : ''

  const body = `<div class="sheet">
  <div class="header">
    <div>
      <h1>出库单</h1>
      <div class="doc-no">单号：${esc(record.outbound_no)}</div>
    </div>
  </div>

  <div class="body-row">
    <div class="left">
      <table class="info-table">
        <tr><td>客户名称</td><td><strong>${esc(record.customer_name)}</strong></td></tr>
        <tr><td>出库日期</td><td>${esc(record.outbound_date)}</td></tr>
        <tr><td>负责人</td><td>${esc(record.owner_name)}</td></tr>
      </table>
    </div>
    ${qrSection}
  </div>

  ${itemsTable(items)}

  <div class="footer">
    <span>莱莎方舟平台 · 发货检验</span>
    <span>打印时间：${esc(printedAt())}</span>
    <span>单号：${esc(record.outbound_no)}</span>
  </div>
</div>`

  return wrapDoc(`出库单 ${record.outbound_no}`, SHEET_CSS, body)
}

// ── 验货单 A4 ─────────────────────────────────────────

// 照片分区：整单照片（item_id 为空或不属于任何明细）在前，其余按明细顺序分组
function groupPhotos(photosDataUrls, photoItemMap) {
  const whole = []
  const byItem = new Map()
  for (const photo of photosDataUrls) {
    const name = photo.item_id != null ? photoItemMap[photo.item_id] : ''
    if (!name) {
      whole.push(photo)
      continue
    }
    if (!byItem.has(photo.item_id)) byItem.set(photo.item_id, { name, photos: [] })
    byItem.get(photo.item_id).photos.push(photo)
  }
  return { whole, groups: [...byItem.values()] }
}

function photoGrid(photos, captionOf) {
  const cells = photos.map(p => `<figure class="photo-cell">
      <img src="${esc(p.dataUrl)}" alt="验货照片">
      <figcaption>${esc(captionOf(p))}</figcaption>
    </figure>`).join('')
  return `<div class="photo-grid">${cells}</div>`
}

export function buildInspectionDoc({ record, items = [], photosDataUrls = [], photoItemMap = {} }) {
  const { whole, groups } = groupPhotos(photosDataUrls, photoItemMap)
  const photoBlocks = [
    whole.length
      ? `<div class="photo-group"><div class="photo-group-title">整单照片</div>${photoGrid(whole, () => '整单照片')}</div>`
      : '',
    ...groups.map(g =>
      `<div class="photo-group"><div class="photo-group-title">${esc(g.name)}</div>${photoGrid(g.photos, () => g.name)}</div>`),
  ].join('')

  const body = `<div class="sheet">
  <div class="header">
    <div>
      <h1>发货验货单</h1>
      <div class="doc-no">出库单号：${esc(record.outbound_no)}</div>
    </div>
  </div>

  <div class="body-row">
    <div class="left">
      <table class="info-table">
        <tr><td>客户名称</td><td><strong>${esc(record.customer_name)}</strong></td></tr>
        <tr><td>提交人</td><td>${esc(record.submitted_by_name)}</td></tr>
        <tr><td>提交时间</td><td>${esc(record.submitted_at)}</td></tr>
      </table>
    </div>
  </div>

  ${itemsTable(items)}

  ${record.remark ? `<div class="remark-section"><div class="remark-label">备注</div>${esc(record.remark)}</div>` : ''}

  ${photoBlocks ? `<div class="photo-section"><h3>验货照片</h3>${photoBlocks}</div>` : ''}

  <div class="footer">
    <span>莱莎方舟平台 · 发货检验</span>
    <span>打印时间：${esc(printedAt())}</span>
    <span>出库单号：${esc(record.outbound_no)}</span>
  </div>
</div>`

  return wrapDoc(`验货单 ${record.outbound_no}`, SHEET_CSS, body)
}
