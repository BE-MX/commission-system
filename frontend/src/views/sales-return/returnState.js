export const RETURN_TYPES = { return_refund: '退货退款', refund_only: '仅退款' }
export const RETURN_STATUSES = { draft: '草稿', effective: '已生效', reversed: '已冲销' }
export const CASH_STATUSES = { not_paid: '未实际付款', paid: '已登记付款', recovered: '资金已收回' }
export const RECEIVING_STATUSES = { awaiting_receipt: '待收货', partially_received: '部分收货', pending_inspection: '待完成检验', inspected: '已检验 · 待权威入库接入', stocked: '已核验入库', rejected: '不合格 · 待处理', not_required: '无需收货' }
export const EVENT_LABELS = { created: '创建草稿', updated: '修改草稿', activated: '退货生效', reversed: '反向更正', deleted: '删除草稿', cash_paid: '登记实际付款', cash_recovered: '登记资金收回', received: '登记收货', inspected: '继续检验', stock_verified: '核验入库' }
export const REASONS = { quality: '质量问题', specification: '规格不符', wrong_goods: '发错商品', negotiated: '协商补偿', other: '其他原因' }
export const label = (dictionary, value) => dictionary[value] || value || '—'
export const amount = value => value === null || value === undefined || value === '' ? '—' : String(value)
export const requestKey = () => globalThis.crypto.randomUUID()

// Preserve decimal strings. The ledger and all totals are calculated by the server.
export function draftPayload(form) {
  return {
    order_id: form.order_id ? String(form.order_id) : '',
    return_type: form.return_type,
    reason_code: form.reason_code,
    reason: (form.reason || '').trim(),
    lines: form.lines.filter(line => line.selected).map(line => ({
      source_key: line.source_key,
      quantity: Number(line.quantity),
      reduction_amount: String(line.reduction_amount ?? '0').trim(),
    })),
    refund_amount: form.refund_amount === '' || form.refund_amount === null ? null : String(form.refund_amount).trim(),
  }
}

export function validateDraft(body) {
  if (!body.order_id) return '请选择原订单'
  if (!body.reason_code || body.reason.length < 2) return '请选择原因并填写至少两个字的具体说明'
  if (!body.lines.length) return '请至少选择一条原订单明细'
  const decimal = /^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/
  if (body.lines.some(line => !decimal.test(line.reduction_amount))) return '货款冲减请输入非负金额，最多两位小数'
  if (body.lines.some(line => !Number.isSafeInteger(line.quantity) || line.quantity <= 0 || line.quantity > 1000000)) return '涉及数量必须是 1 至 1000000 的整数'
  if (body.refund_amount !== null && !decimal.test(body.refund_amount)) return '现金退款请输入非负金额，最多两位小数'
  return ''
}

export const fingerprint = body => JSON.stringify(body)
export const isUncertain = failure => !failure?.response || failure.response.status >= 500

const decimalKey = value => {
  if (value === null) return null
  const [whole, fraction = ''] = String(value).split('.')
  const significant = fraction.replace(/0+$/, '')
  return significant ? `${whole}.${significant}` : whole
}
export function draftComparison(body) {
  return fingerprint({ ...body, refund_amount: decimalKey(body.refund_amount), lines: body.lines.map(line => ({ ...line, reduction_amount: decimalKey(line.reduction_amount) })).sort((a, b) => a.source_key.localeCompare(b.source_key)) })
}

/** Reuse the exact immutable body and key until an uncertain write is reconciled. */
export function createIntent(action, body) {
  return { action, body: JSON.parse(JSON.stringify(body)), key: body.request_key || requestKey() }
}
