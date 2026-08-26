import { formatBeijingDateTime } from '../../../utils/datetime.js'

export function formatInvoiceDateTime(value) {
  return formatBeijingDateTime(value, { seconds: false })
}
