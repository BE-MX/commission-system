// Fee presentation for the review step. Pure; amounts stay exact decimal strings.
import { money } from '../presentation.mjs'

export function feeSummary(quote) {
  const estimate = quote?.fee_estimate
  if (!estimate) {
    return { confirmed: false, rows: [['Shipping & other charges', 'Pending review'], ['Final total', 'To be confirmed']],
      note: 'Shipping and any additional charges will be included in a proposal for your confirmation.' }
  }
  const weight = estimate.weight_grams == null ? 'To be confirmed' : formatWeight(estimate.weight_grams)
  if (estimate.status !== 'confirmed') {
    const reason = estimate.reason === 'over_limit'
      ? `Orders over ${formatWeight(String(estimate.manual_above_grams))} are quoted individually.`
      : 'Some product weights need confirmation.'
    return { confirmed: false, weight, rows: [['Total weight', weight], ['Shipping', 'Quoted by your representative'],
      ['Final total', 'To be confirmed']], note: `${reason} Your representative will send shipping for your confirmation.` }
  }
  const rows = [['Total weight', weight], ['Shipping', money(estimate.shipping_amount)]]
  if (estimate.surcharge_amount !== '0.00') rows.push([estimate.surcharge_name, money(estimate.surcharge_amount)])
  rows.push(['Total', money(estimate.total_amount)])
  return { confirmed: true, weight, rows, total: estimate.total_amount,
    note: 'By submitting you confirm these complete terms. Your representative reviews them before issuing the formal PI.' }
}

export function formatWeight(grams) {
  const value = grams == null || grams === '' ? NaN : Number(grams)
  if (!Number.isFinite(value)) return '—'
  return value >= 1000 ? `${+(value / 1000).toFixed(2)} kg` : `${+value.toFixed(1)} g`
}

export function surchargeLabel(term) {
  return Number(term.surcharge_percent) > 0 ? `+${+Number(term.surcharge_percent).toFixed(2)}% payment surcharge` : 'No surcharge'
}
