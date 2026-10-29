// Only these list parameters are restored; unknown URL values never reach the API.
import { OUTBOUND_STATE_LABELS } from './outboundStates.js'

export const OUTBOUND_VIEW_KEYS = ['keyword', 'order_id', 'outbound_state', 'inspection_status', 'date_from', 'date_to', 'page', 'page_size', 'sort_field', 'sort_order']
const SORT_FIELDS = ['outbound_no', 'order_id', 'customer_name', 'outbound_date', 'item_count', 'outbound_state', 'status', 'photo_count']
export const emptyOutboundFilters = () => ({ keyword: '', orderId: '', outboundState: '', inspectionStatus: '', dateRange: [] })
const text = value => typeof value === 'string' ? value : ''
function validDay(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number)
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return y >= 1900 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1]
}
export function readOutboundListState(query = {}) {
  const start = text(query.date_from), end = text(query.date_to)
  const page = Number(text(query.page)), pageSize = Number(text(query.page_size))
  const sortField = text(query.sort_field), sortOrder = text(query.sort_order), outboundState = text(query.outbound_state)
  return {
    searchForm: {
      keyword: text(query.keyword), orderId: text(query.order_id),
      outboundState: Object.hasOwn(OUTBOUND_STATE_LABELS, outboundState) ? outboundState : '',
      inspectionStatus: ['none', 'draft', 'submitted'].includes(query.inspection_status) ? query.inspection_status : '',
      dateRange: validDay(start) && validDay(end) && start <= end ? [start, end] : [],
    },
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    pageSize: [20, 50, 100].includes(pageSize) ? pageSize : 20,
    sortParams: SORT_FIELDS.includes(sortField) && ['asc', 'desc'].includes(sortOrder) ? { sort_field: sortField, sort_order: sortOrder } : {},
  }
}
export function outboundListQuery(view, current = {}) {
  const query = Object.fromEntries(Object.entries(current).filter(([key]) => !OUTBOUND_VIEW_KEYS.includes(key)))
  const form = view.searchForm
  for (const [key, value] of Object.entries({ keyword: form.keyword, order_id: form.orderId, outbound_state: form.outboundState, inspection_status: form.inspectionStatus, date_from: form.dateRange?.[0], date_to: form.dateRange?.[1], page: view.page > 1 ? String(view.page) : '', page_size: view.pageSize !== 20 ? String(view.pageSize) : '', ...view.sortParams })) {
    if (value !== undefined && value !== null && value !== '') query[key] = String(value)
  }
  return query
}
export const querySignature = query => JSON.stringify(Object.entries(query).sort(([a], [b]) => a.localeCompare(b)))
export function outboundFilterSummary(form, outboundLabels, inspectionLabels) {
  return [
    ['keyword', '关键词', form.keyword], ['outboundState', '出库状态', outboundLabels[form.outboundState]],
    ['inspectionStatus', '检验状态', inspectionLabels[form.inspectionStatus]],
    ['dateRange', '出库日期', form.dateRange?.length === 2 ? form.dateRange.join(' 至 ') : ''], ['orderId', '订单 ID', form.orderId],
  ].filter(([, , value]) => value).map(([key, label, value]) => ({ key, label, value }))
}

export function outboundSortSummary(sort = {}) {
  const labels = { outbound_no: '出库单号', order_id: '订单 ID', customer_name: '客户名称', outbound_date: '出库日期', item_count: '明细 / 数量', outbound_state: '出库单状态', status: '检验状态', photo_count: '照片数' }
  return Object.hasOwn(labels, sort.sort_field) && ['asc', 'desc'].includes(sort.sort_order)
    ? [{ key: 'sort', label: '排序', value: `${labels[sort.sort_field]} · ${sort.sort_order === 'asc' ? '升序' : '降序'}` }]
    : []
}
