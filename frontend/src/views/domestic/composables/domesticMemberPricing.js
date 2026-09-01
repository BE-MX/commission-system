const CHANGE_REASON_LABELS = {
  membership_changed: '客户会员等级已变化',
  base_price_changed: '产品原始价已调整',
  pricing_rule_changed: '优惠规则已更新',
  discount_price_changed: '优惠价已更新',
  pricing_version_changed: '优惠规则版本已更新',
  rule_changed: '优惠规则已更新',
  price_missing: '原始价已删除，需重新维护',
}

export function membershipPreview(amount) {
  const value = Number(amount || 0)
  if (value >= 100000) return '至尊会员'
  if (value >= 30000) return '黑卡会员'
  if (value >= 10000) return '银卡会员'
  return '普通客户'
}

export function membershipLevelLabel(level) {
  return ({ silver: '银卡会员', black: '黑卡会员', supreme: '至尊会员' })[level] || '非会员'
}

export function quoteChangeReasonLabel(reason) {
  return CHANGE_REASON_LABELS[reason] || '报价内容已变化'
}

export function quoteStatusLabel(status) {
  return ({ quoting: '报价中', pending: '待报价', missing_base_price: '缺原价', priced: '已报价' })[status] || '待报价'
}

export function invalidateItemQuote(item) {
  item.quoteStatus = 'pending'
  item.expectedQuote = null
  item.quote = null
}

export function buildQuoteRequest(form, normalizeAttrs) {
  return {
    customer_id: form.customer_id || null,
    items: form.items.map(item => ({
      client_key: item.key,
      attrs: normalizeAttrs(item.attrs),
    })),
  }
}

export function applyQuoteResult(items, response) {
  const byKey = new Map((response?.items || []).map(row => [row.client_key, row]))
  for (const item of items) {
    const quote = byKey.get(item.key)
    if (!quote) continue
    item.quoteStatus = quote.status
    item.quote = quote
    item.expectedQuote = quote.status === 'priced' ? quote.expected_quote : null
  }
}

export function hasBlockingPrice(items) {
  return items.some(item => item.quoteStatus !== 'priced' || !item.expectedQuote)
}

function imagePaths(value) {
  return (value || []).map(file => file.path)
}

export function buildCreateItems(items, normalizeAttrs) {
  return items.map(item => ({
    client_key: item.key,
    attrs: normalizeAttrs(item.attrs),
    order_qty: item.order_qty,
    expected_quote: item.expectedQuote,
    hairstyle: item.hairstyle || null,
    hairstyle_images: imagePaths(item.hairstyle_images),
    color: item.color || null,
    color_images: imagePaths(item.color_images),
    style_requirement: item.style_requirement || null,
    style_images: imagePaths(item.style_images),
    remark: item.remark || null,
    remark_images: imagePaths(item.remark_images),
  }))
}

const QUOTE_FIELDS = [
  'original_price', 'base_price_version', 'discount_price',
  'membership_level', 'pricing_rule', 'pricing_version',
]

function expectedQuoteFromCurrent(row) {
  return Object.fromEntries(QUOTE_FIELDS.map(field => [field, row[field]]))
}

export function applyQuoteChange(items, currentExpectedQuotes, requestIdFactory) {
  const byKey = new Map((currentExpectedQuotes || []).map(row => [row.client_key, row]))
  for (const item of items) {
    const current = byKey.get(item.key)
    if (!current) continue
    item.expectedQuote = expectedQuoteFromCurrent(current)
    item.quoteStatus = 'priced'
    item.quote = {
      ...(item.quote || {}), status: 'priced', client_key: item.key,
      original_price: current.original_price,
      discount_price: current.discount_price,
      discount_amount: Number(current.original_price) - Number(current.discount_price),
      pricing_rule: current.pricing_rule,
      expected_quote: item.expectedQuote,
    }
  }
  return requestIdFactory()
}

export function buildDraftSubmitPayload(detail, requestIdFactory) {
  const expectedQuotes = detail?.current_expected_quotes?.length
    ? detail.current_expected_quotes
    : (detail?.items || []).map(item => ({
      client_key: null,
      item_id: item.id,
      original_price: item.original_price,
      base_price_version: item.base_price_version,
      discount_price: item.unit_price,
      membership_level: item.membership_level_snapshot,
      pricing_rule: item.pricing_rule,
      pricing_version: item.pricing_version,
    }))
  return {
    request_id: requestIdFactory(),
    expected_quotes: expectedQuotes,
  }
}

export function quoteChangedDetail(error) {
  const detail = error?.response?.data?.detail || error?.response?.data?.data || error?.detail
  return detail?.error_code === 'DOMESTIC_QUOTE_CHANGED' ? detail : null
}
