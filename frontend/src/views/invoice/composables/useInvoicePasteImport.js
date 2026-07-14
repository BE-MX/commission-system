export const STANDARD_FIELDS = ['product', 'length', 'color', 'weight', 'quantity', 'unit_price']

const HEADER_ALIASES = new Map([
  ['product', ['product', 0]],
  ['产品名称product', ['product', 1]],
  ['product_name', ['product', 2]],
  ['产品名称', ['product', 3]],
  ['产品', ['product', 3]],
  ['length', ['length', 0]],
  ['长度', ['length', 1]],
  ['color', ['color', 0]],
  ['colour', ['color', 0]],
  ['颜色', ['color', 1]],
  ['色号', ['color', 1]],
  ['weight', ['weight', 0]],
  ['netweightgrams', ['weight', 0]],
  ['重量', ['weight', 1]],
  ['克重', ['weight', 1]],
  ['quantity', ['quantity', 0]],
  ['qty', ['quantity', 0]],
  ['数量', ['quantity', 1]],
  ['unitprice', ['unit_price', 0]],
  ['price/piece', ['unit_price', 0]],
  ['price', ['unit_price', 1]],
  ['单价', ['unit_price', 1]],
  ['成交价', ['unit_price', 1]],
])

function normalizeHeader(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, '')
}

function resolveHeaderMapping(headers) {
  const selected = new Map()
  headers.forEach((header, index) => {
    const alias = HEADER_ALIASES.get(normalizeHeader(header))
    if (!alias) return
    const [field, priority] = alias
    const current = selected.get(field)
    if (!current || priority < current.priority) selected.set(field, { index, priority })
  })

  const hasHeader = selected.size > 0
  if (!hasHeader) {
    return {
      hasHeader: false,
      fields: Object.fromEntries(STANDARD_FIELDS.map((field, index) => [field, index])),
      ignoredHeaders: [],
    }
  }

  const fields = Object.fromEntries([...selected].map(([field, value]) => [field, value.index]))
  const missing = STANDARD_FIELDS.filter(field => fields[field] == null)
  if (missing.length) throw new Error(`缺少必填列：${missing.join(', ')}`)
  const selectedIndexes = new Set(Object.values(fields))
  return {
    hasHeader: true,
    fields,
    ignoredHeaders: headers.filter((_, index) => !selectedIndexes.has(index)),
  }
}

function mapCells(cells, mapping, sourceRow) {
  const indexes = Object.values(mapping.fields)
  if (indexes.some(index => index >= cells.length)) throw new Error(`第 ${sourceRow} 行列数不足`)
  return Object.fromEntries([
    ['source_row', sourceRow],
    ...STANDARD_FIELDS.map(field => [field, String(cells[mapping.fields[field]] ?? '').trim()]),
  ])
}

export function parseInvoiceClipboard(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((line, index) => ({ sourceRow: index + 1, cells: line.split('\t') }))
    .filter(entry => entry.cells.some(cell => cell.trim()))
  if (!lines.length) throw new Error('请先粘贴 Excel 明细')

  const mapping = resolveHeaderMapping(lines[0].cells)
  if (!mapping.hasHeader && lines[0].cells.length !== STANDARD_FIELDS.length) {
    throw new Error('无法识别列结构，请复制包含表头的数据')
  }
  const dataLines = mapping.hasHeader ? lines.slice(1) : lines
  if (!dataLines.length) throw new Error('导入数据至少包含 1 行')
  if (dataLines.length > 200) throw new Error('单次最多导入 200 行')

  const warnings = []
  if (!mapping.hasHeader) warnings.push('未检测到表头，已按标准列顺序识别')
  if (mapping.ignoredHeaders.length) {
    warnings.push(`已忽略列：${mapping.ignoredHeaders.join('、')}`)
  }
  return {
    rows: dataLines.map(entry => mapCells(entry.cells, mapping, entry.sourceRow)),
    mapping: mapping.fields,
    ignoredHeaders: mapping.ignoredHeaders,
    warnings,
  }
}

export function mapPreviewRowToInvoiceLine(row, batchFingerprint, orderType) {
  const normalized = row.normalized
  const matched = row.matched_product || {}
  const price = Number(normalized.unit_price)
  return {
    item_type: matched.product_id ? 'stock' : (orderType === 'production' ? 'custom' : 'stock'),
    product_id: matched.product_id || null,
    sku_id: matched.sku_id || null,
    product_name: matched.product_name || '',
    product_display: normalized.product,
    net_weight_grams: normalized.weight,
    curl: '',
    model: matched.model || '',
    color: normalized.color,
    length: normalized.length,
    quantity: Number(normalized.quantity),
    price_per_piece: price,
    price_source: row.price_source || 'manual',
    standard_price: row.standard_price == null ? null : Number(row.standard_price),
    customer_price: row.customer_price == null ? null : Number(row.customer_price),
    total_price: Math.round(price * Number(normalized.quantity) * 100) / 100,
    _importBatchFingerprint: batchFingerprint,
  }
}

export function hasImportedBatch(items, fingerprint) {
  return Boolean(fingerprint) && items.some(item => item._importBatchFingerprint === fingerprint)
}
