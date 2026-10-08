import { money } from './presentation.mjs'
export const orderStatuses = Object.freeze({ submitted: 'Under review', awaiting_customer: 'Your confirmation needed', ready_for_review: 'Awaiting final approval', invoice_created: 'PI created', rejected: 'Request declined', cancelled: 'Cancelled' })
export const statusLabel = status => orderStatuses[status] || 'Status unavailable'
export const totalLabel = order => order.total_amount == null ? 'Product subtotal · charges pending'
  : ({ awaiting_customer: 'Proposed total', ready_for_review: 'Accepted total', invoice_created: 'Last published total' })[order.status] || 'Request total'
export const eventLabel = event => ({ 'order.submitted': 'Request received', 'order.proposed': 'Proposal prepared', 'order.accepted': 'Proposal accepted', 'order.proposal_rejected': 'Changes requested', 'order.cancelled': 'Request cancelled', 'order.invoice_created': 'PI created', 'order.pi_proposed': 'Updated PI proposed', 'order.pi_accepted': 'PI update accepted', 'order.pi_rejected': 'PI update declined', 'order.pi_published': 'Confirmed PI published', 'order.pi_voided': 'PI voided', 'order.rejected': 'Request declined' })[event] || 'Request updated'
export const piLabel = status => ({ current: 'Your confirmed PI is ready.', pending_customer: 'Updated PI awaiting your confirmation.', accepted: 'PI update accepted. Awaiting publication.', withdrawn: 'Your PI is being revised.', voided: 'This PI has been voided.', rejected: 'PI update declined. Awaiting your representative.' })[status] || 'Your PI is not available for download yet.'
const labels = { currency: 'Currency', product_amount: 'Product subtotal', shipping_amount: 'Shipping', packaging_amount: 'Packaging', surcharge_amount: 'Additional charges', surcharge_name: 'Charge description', total_amount: 'Total', fees_status: 'Charges status', delivery: 'Delivery details', payment_terms: 'Payment terms', remark: 'Notes', commercial_header: 'PI details', contact_name: 'Contact', phone: 'Phone', address_line1: 'Address', address_line2: 'Address line 2', city: 'City', region: 'Region', postal_code: 'Postal code', country_code: 'Country', code: 'Terms code', display_text: 'Terms', deposit_percent: 'Deposit percent', invoice_no: 'PI number', customer_name: 'Customer', invoice_date: 'PI date', express_channel: 'Shipping method', contact_email: 'Customer email', sales_user_name: 'Representative', sales_phone: 'Representative phone', sales_email: 'Representative email', packaging_quantity: 'Packages' }
export const fieldLabel = key => labels[key] || 'Detail'
export function fieldValue(key, value) {
  if (key.endsWith('_amount')) return money(value)
  if (value == null || value === '') return 'Not specified'
  if (typeof value === 'object') return Object.entries(value).filter(([name]) => labels[name]).map(([name, entry]) => `${fieldLabel(name)}: ${fieldValue(name, entry)}`).join('\n') || 'Not specified'
  if (key === 'fees_status') return value === 'confirmed' ? 'Confirmed' : 'Pending confirmation'
  return String(value)
}
