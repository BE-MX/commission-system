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

export function membershipChangeLabel(change) {
  if (!change) return ''
  return `${membershipLevelLabel(change.from)} → ${membershipLevelLabel(change.to)}`
}

export function pricingRuleLabelForQuote(quote) {
  if (!quote) return '报价已更新'
  const member = membershipLevelLabel(quote.membership_level)
  if (quote.pricing_rule === 'base_price') return '非会员原价'
  if (quote.pricing_rule === 'member_fixed') return `${member}固定会员价`
  if (quote.pricing_rule === 'member_fixed_capped') return '命中固定会员价，但原价更低，已按原价'
  if (quote.pricing_rule === 'member_reduction') {
    const reduction = Number(quote.original_price || 0) - Number(quote.discount_price || 0)
    return `${member}立减 ¥${reduction.toFixed(2)}`
  }
  return '报价已更新'
}

export function quoteChangeRows(detail, itemLabel = key => key || '明细') {
  return (detail?.changes || []).map(change => {
    const before = change.previous_quote
    const after = change.current_quote
    const reasons = (change.reasons || []).map(quoteChangeReasonLabel).join('、') || '报价内容已变化'
    if (!after) return `${itemLabel(change.client_key, change.item_id)}：${reasons}`
    return [
      `${itemLabel(change.client_key, change.item_id)}：`,
      `原价 ¥${Number(before?.original_price || 0).toFixed(2)} → ¥${Number(after.original_price || 0).toFixed(2)}`,
      `优惠价 ¥${Number(before?.discount_price || 0).toFixed(2)} → ¥${Number(after.discount_price || 0).toFixed(2)}`,
      `规则 ${pricingRuleLabelForQuote(before)} → ${pricingRuleLabelForQuote(after)}`,
      `原因 ${reasons}`,
    ].join('；')
  })
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().filter(key => key !== 'request_id')
        .map(key => [key, canonicalize(value[key])]),
    )
  }
  return value
}

export function payloadFingerprint(payload) {
  return JSON.stringify(canonicalize(payload))
}

export function ensureRequestIdentity(current, payload, requestIdFactory) {
  const fingerprint = payloadFingerprint(payload)
  if (current?.fingerprint === fingerprint && current.requestId) return current
  return { fingerprint, requestId: requestIdFactory() }
}

export function priceImpactLabel(impact) {
  if (!impact?.price_key) return '未取得共享价格影响范围'
  const key = impact.price_key
  const type = key.product_type === 'cap' ? '头套' : (key.product_type === 'piece' ? '发片' : key.product_type)
  return `${type} / ${key.craft} / ${key.length}，共影响 ${Number(impact.affected_sku_count || 0)} 个 SKU`
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
      status: 'priced', client_key: item.key,
      original_price: current.original_price,
      discount_price: current.discount_price,
      discount_amount: Number(current.original_price) - Number(current.discount_price),
      pricing_rule: current.pricing_rule,
      pricing_rule_label: pricingRuleLabelForQuote(current),
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
