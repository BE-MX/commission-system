import { requireAmount, toUnits } from './decimal'

export function allocationPayload(form, payment, detail) {
  if (!detail || detail.invoice.id !== form.invoice_id) throw new Error('请选择并加载订单应收')
  const target = detail.items.find(row => row.id === form.receivable_id && !row.cancelled)
  if (!target || target.currency !== payment.currency) throw new Error('请选择同币种有效应收')
  if (payment.status !== 'confirmed') throw new Error('付款尚未财务确认')
  if (!form.business_date) throw new Error('请选择核销业务日期')
  const amount = requireAmount(form.amount, '核销金额', { allowZero: false })
  if (toUnits(amount) > toUnits(payment.available_amount) || toUnits(amount) > toUnits(target.remaining_amount)) throw new Error('核销金额超过付款余额或应收余额')
  const deposit = form.purpose === 'presale_deposit'
  if (deposit && (detail.invoice.order_type !== 'presale' || target.kind !== 'goods')) throw new Error('首款仅适用于预售商品应收')
  const settlement = detail.settlements.find(row => row.id === form.settlement_id && row.state === 'awaiting_payment')
  if (!deposit && detail.invoice.order_type === 'presale' && !settlement) throw new Error('预售批次款必须选择待收款结算批次')
  if (!deposit && form.settlement_id && !settlement) throw new Error('所选结算批次不可核销')
  if (!deposit && target.kind === 'freight' && target.settlement_id && settlement?.id !== target.settlement_id) throw new Error('运费应收必须核销到对应发货批次')
  return { expected_version: payment.version, invoice_id: form.invoice_id, receivable_id: target.id, purpose: form.purpose, settlement_id: deposit ? null : form.settlement_id || null, amount, business_date: form.business_date }
}
