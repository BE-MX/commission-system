// 整单粘贴（2026-09-23）：把 Excel 发票整段内容（如 C6:I23）一次性解析为
// 客户/联系方式/收货地址 + 折扣/包装/运费/手续费 + 付款方式/快递渠道。
// 产品明细行不在此解析，继续走「从 Excel 粘贴」（InvoicePasteImport）。
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from './invoiceSettlement.js'
import { mapCells, resolveHeaderMapping } from './useInvoicePasteImport.js'

// 引号感知 TSV 解析：Excel 复制时含换行/制表符的单元格（如 Delivery address 的
// 多行地址）会用双引号包裹，内部 " 转义为 ""。朴素 split('\n') 会把地址截成两行。
function tokenizeClipboard(text) {
  const rows = []
  let row = []
  let cell = ''
  let inQuotes = false
  const pushCell = () => { row.push(cell); cell = '' }
  const pushRow = () => {
    pushCell()
    if (row.some(value => value.trim())) rows.push(row)
    row = []
  }
  const src = String(text || '')
  for (let index = 0; index < src.length; index += 1) {
    const char = src[index]
    if (inQuotes) {
      if (char === '"') {
        if (src[index + 1] === '"') { cell += '"'; index += 1 } else inQuotes = false
      } else cell += char
    } else if (char === '"' && cell === '') inQuotes = true
    else if (char === '\t') pushCell()
    else if (char === '\n') pushRow()
    else if (char !== '\r') cell += char
  }
  pushRow()
  return rows
}

function parseAmount(value) {
  const cleaned = String(value ?? '').replace(/[$¥,\s]/g, '')
  if (!cleaned) return null
  const number = Number(cleaned)
  return Number.isFinite(number) ? number : null
}

// 金额取行内最后一个数值单元格（模板里金额恒在最右侧 I 列；
// packages 行左侧还有数量等数字，取最后一个才落到 I 列总额）
function lastNumberCell(cells) {
  for (let index = cells.length - 1; index >= 0; index -= 1) {
    const amount = parseAmount(cells[index])
    if (amount != null) return amount
  }
  return null
}

function nextTextCell(cells, labelIndex) {
  for (let index = labelIndex + 1; index < cells.length; index += 1) {
    const value = String(cells[index] ?? '').trim()
    if (value) return value
  }
  return ''
}

const PAYMENT_ALIASES = [
  [/^paypal$/, 'PayPal'],
  [/^(tt|t\/t|t-t|电汇)$/, 'TT'],
  [/^(现金|cash)$/, '现金'],
  [/^(支付宝|alipay)$/, '支付宝'],
  [/^(微信|wechat|weixin|wechatpay)$/, '微信'],
  [/对公.*莱莎|莱莎.*对公/, '对公转账（莱莎）'],
  [/对公.*旭和|旭和.*对公/, '对公转账（旭和）'],
]

// 付款方式归一：先与选项精确匹配（忽略大小写），再走常见别名；识别不出返回 null
export function resolvePaymentMethod(raw) {
  const value = String(raw || '').trim()
  if (!value) return null
  const exact = PAYMENT_METHOD_OPTIONS.find(option => option.toLowerCase() === value.toLowerCase())
  if (exact) return exact
  const normalized = value.toLowerCase().replace(/\s+/g, '')
  for (const [pattern, option] of PAYMENT_ALIASES) {
    if (pattern.test(normalized)) return option
  }
  if (normalized.includes('信保')) {
    const shop = ['大莱莎', '小莱莎', '新莱莎'].find(name => normalized.includes(name))
    if (shop) return normalized.includes('报关') ? `${shop}信保（报关）` : `${shop}信保（便捷发货）`
  }
  return null
}

// 快递渠道归一：识别不出返回 null（模板里「Paymetn term」行常放联邦普货等渠道）
export function resolveExpressChannel(raw) {
  const value = String(raw || '').trim().toLowerCase()
  if (!value) return null
  if (value.includes('fedex') || value.includes('联邦')) return 'FEDEX'
  if (value.includes('dhl')) return 'DHL'
  if (value.includes('顺丰') || value === 'sf') return '顺丰'
  return EXPRESS_CHANNEL_OPTIONS.find(option => option.toLowerCase() === value) || null
}

const normalizeCell = value => String(value || '').trim().toLowerCase().replace(/\s+/g, '')

// 产品明细表头行：存在 normalized 为 product 的单元格（Product_name/产品名称不算）
function findProductHeaderIndex(rows) {
  return rows.findIndex(cells => cells.some(cell => normalizeCell(cell) === 'product'))
}

export function parseWholeOrderClipboard(text) {
  const rows = tokenizeClipboard(text)
  if (!rows.length) throw new Error('请先粘贴 Excel 整单内容')
  const result = {
    customer_name: '', contact_phone: '', contact_email: '', delivery_address: '',
    discount_total: null, packaging_fee: null, shipping_fee: null, handling_fee: null,
    payment_method: null, payment_raw: '', express_channel: null, express_raw: '',
    product_rows: [], ignored_rows: 0,
  }
  const paymentCandidates = []
  const productHeaderIndex = findProductHeaderIndex(rows)
  let productMapping = null
  rows.forEach((cells, rowIndex) => {
    // 表头行本身：建立列映射后跳过（避免 'Total Price' 命中 total 忽略规则）
    if (rowIndex === productHeaderIndex) {
      try {
        productMapping = resolveHeaderMapping(cells)
      } catch {
        productMapping = null
      }
      return
    }
    // 产品区（表头之下）且行内有足够有效列：按产品明细行处理，不走关键词规则——
    // 产品名可能含 hair/tool 等词；费用行（hair price/packages 等）有效列少，不会误判
    const nonEmptyCells = cells.filter(cell => String(cell ?? '').trim()).length
    if (productMapping && rowIndex > productHeaderIndex && nonEmptyCells >= 5) {
      try {
        result.product_rows.push(mapCells(cells, productMapping, result.product_rows.length + 1))
      } catch { /* 列数不足的行放弃，留给后端校验兜底 */ }
      return
    }
    for (let index = 0; index < cells.length; index += 1) {
      const label = String(cells[index] ?? '').trim().toLowerCase()
      if (!label) continue
      if (/^to[:：]?$/.test(label)) { result.customer_name ||= nextTextCell(cells, index); break }
      if (/^tel\/fax/.test(label)) { result.contact_phone ||= nextTextCell(cells, index); break }
      if (/^e-?mail/.test(label)) { result.contact_email ||= nextTextCell(cells, index); break }
      if (label.includes('delivery')) { result.delivery_address ||= nextTextCell(cells, index); break }
      // 忽略行：hair / tool / total / final 关键词一律不提取
      if (label.includes('hair') || label.includes('tool') || label.includes('total') || label.includes('final')) {
        result.ignored_rows += 1
        break
      }
      // 折扣总价：包含 discount 且不包含 after
      if (label.includes('discount') && !label.includes('after')) {
        result.discount_total = Math.abs(lastNumberCell(cells) ?? 0)
        break
      }
      if (label.includes('package')) { result.packaging_fee = lastNumberCell(cells); break }
      if (label.includes('shipping')) { result.shipping_fee = lastNumberCell(cells); break }
      if (label.includes('handling')) {
        result.handling_fee = lastNumberCell(cells)
        const candidate = nextTextCell(cells, index)
        if (candidate) paymentCandidates.push(candidate)
        break
      }
      // 模板把 Payment 误拼为 Paymetn，两种都认；其右侧内容为付款方式候选
      if (label.includes('payment') || label.includes('paymetn')) {
        const candidate = nextTextCell(cells, index)
        if (candidate) paymentCandidates.push(candidate)
        break
      }
    }
  })
  for (const candidate of paymentCandidates) {
    if (!result.payment_method) {
      const method = resolvePaymentMethod(candidate)
      if (method) { result.payment_method = method; result.payment_raw = candidate; continue }
    }
    if (!result.express_channel) {
      const channel = resolveExpressChannel(candidate)
      if (channel) { result.express_channel = channel; result.express_raw = candidate }
    }
  }
  // 付款方式候选存在但一项都没识别出来：原文带出，预览里提示人工选择
  if (!result.payment_method && !result.express_channel && paymentCandidates.length) {
    result.payment_raw = paymentCandidates[0]
  }
  return result
}
