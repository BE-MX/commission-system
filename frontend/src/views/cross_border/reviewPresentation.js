import { formatMoney } from '../../utils/money.js'
export const selectable = row => row.row_type === 'declaration' && !row.blocking && !row.excluded && !row.voided
export const money = value => formatMoney(value, { missing: '—' })
export const issueType = issue => issue.blocking ? 'danger' : 'warning'
export const actionsFor = row => {
  if (row.row_type !== 'declaration' || row.excluded || row.voided) return []
  if (row.exported) return row.suspected_changed ? [{ action: 'void', label: '作废旧条目' }] : []
  const codes = (row.issues || []).map(issue => issue.code)
  return [
    ...(codes.includes('not_picked_up') ? [{ action: 'confirm_shipped', label: '确认已发' }] : []),
    ...(codes.some(code => ['ambiguous_match', 'unknown_product_amount'].includes(code)) ? [{ action: 'assign_ticket', label: '指定配对' }] : []),
    ...(row.suspected_changed ? [{ action: 'void', label: '作废旧条目' }] : []),
    { action: 'exclude', label: '本单不报' },
  ]
}

export const actionLabels = { confirm_shipped: '确认已发', assign_ticket: '指定配对', exclude: '本单不报', void: '作废旧条目', confirm_suspected: '确认疑似修改', import: '导入申报', export: '导出报关文件' }
export const issueHints = {
  no_invoice: '方舟没有同一阿里订单号的 DHL9610 便捷发货发票，请核对订单号和发票。',
  no_waybill: '对应发票还没有关联运单，请先在验货单上传物流单。',
  amount_mismatch: '申报金额与未配对票的应付合计不一致。请核对 DHL 原始申报及发票费用，修正后重新导入。参考票仅用于比较，不代表已配对。',
  split_below_floor: '本票申报低于已出库产品金额，请核对 DHL 商品金额，修正后重新导入。',
  split_total_mismatch: '分票已全部发完，各票申报合计与发票应付合计不一致，请核对各票金额。',
  split_incomplete: '分票组还没有全部发完，合计暂不能核验；不影响当前已通过票导出。',
  unknown_product_amount: '本票出库明细无法对应到发票明细。请人工核对产品与数量，再指定对应运单。',
  ambiguous_match: '同号存在多个可配对运单，系统不能唯一判断。请核对金额、出库和运单后指定配对。',
  missing_receipt: '还没有同号同额收款单，请导入 DHL 最新收款单文件。',
  orphan_receipt: '收款单暂无同号同额订单，请导入 DHL 最新订单文件后重新核对。',
  suspected_changed: '旧条目未出现在新导入的同号订单中。请核对 DHL，已被修改的旧条目可作废；导出同号订单时必须确认。',
  not_picked_up: '运单尚无有效揽收事件。可立即刷新物流；确认货物已交给 DHL 时，可填写原因确认已发。',
  invoice_cancelled: '关联发票已取消，请不要在 DHL 提交该申报，核对后选择本单不报。',
  ticket_without_declaration: '此票已揽收但没有匹配申报，请核对 DHL 并导入最新订单文件。',
  unit_mismatch: '申报单位不是 015（条），请核对 DHL 明细；此提醒不阻断导出。',
  non_dhl: '此发票关联了非 DHL 运单，请核对承运商与快递渠道。',
  non_usd: '发票币种不是 USD，系统不会自动换算，请核对原始发票与申报币种。',
  non_usd_source: 'DHL 源文件币种不是 USD，系统不会自动换算，请修正来源数据后重新导入。',
  go_live_not_configured: '尚未配置跨境申报上线日期，请联系管理员配置后重新核对。',
  exported_rebind: '此票在报关导出后更换过运单，请对照原报关文件核实运单关联。',
  mixed_waybill: '同一运单还包含非 DHL9610 发票，本页金额只按核对范围内的发票计算。',
  split_missing_declaration: '分票组存在尚未匹配申报的票，请补齐申报后核对组合计。',
}
export function accountingTime(value) {
  const text = String(value || '')
  return /^\d{14}$/.test(text) ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)} ${text.slice(8, 10)}:${text.slice(10, 12)}:${text.slice(12, 14)}` : text || '—'
}
export function ticketQuantities(ticket) {
  const parts = ticket?.parts || []
  if (!parts.length || parts.some(part => part.quantities == null)) return null
  return { shipped: parts.reduce((sum, part) => sum + Object.values(part.quantities).reduce((n, value) => n + Number(value), 0), 0), total: parts.reduce((sum, part) => sum + Object.values(part.expected || {}).reduce((n, value) => n + Number(value), 0), 0) }
}
