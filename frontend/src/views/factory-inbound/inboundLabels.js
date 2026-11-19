export const recognitionLabels = {
  queued: '排队中', running: '识别中', done: '待核对', failed: '识别失败',
}

export const lineStatuses = {
  matched: { label: '已匹配', tone: 'success' },
  confirm: { label: '待核对', tone: 'warning' },
  choose: { label: '待选择', tone: 'warning' },
  decide: { label: '待决定', tone: 'warning' },
  blocked: { label: '无法匹配', tone: 'danger' },
  skipped: { label: '不入库', tone: 'info' },
}

export const noteStatus = note => note.status === 'voided' ? '已作废' : recognitionLabels[note.recognition_status]
const recognitionTones = { queued: 'info', running: 'info', done: 'warning', failed: 'danger' }
export const noteTone = note => note.status === 'voided' ? 'muted' : recognitionTones[note.recognition_status] || 'muted'

// 手机核对页的进度统计：已提交批次、已匹配、不入库算「已处理」，其余需要人处理。
const tallyKinds = [
  { key: 'submitted', label: '已提交', tone: 'info', handled: true },
  { key: 'matched', label: '已匹配', tone: 'success', handled: true },
  { key: 'pending', label: '待处理', tone: 'warning', handled: false },
  { key: 'blocked', label: '无法匹配', tone: 'danger', handled: false },
  { key: 'skipped', label: '不入库', tone: 'muted', handled: true },
]
export function lineTally(lines) {
  const counts = {}
  for (const line of lines) {
    const key = line.batch_id ? 'submitted'
      : ['confirm', 'choose', 'decide'].includes(line.match_status) ? 'pending' : line.match_status
    counts[key] = (counts[key] || 0) + 1
  }
  return tallyKinds.filter(kind => counts[kind.key]).map(kind => ({ ...kind, count: counts[kind.key] }))
}
export const pendingRecognition = note => ['queued', 'running'].includes(note?.recognition_status)
export const deliveryDate = note => note.delivery_month && note.delivery_day ? note.delivery_month + '月' + note.delivery_day + '日' : '日期待核对'
export const orderLabel = order => (order.kind === 'invoice' ? '发票生产单 ' : '生产备货单 #') + order.ref

export function targetLabel(line) {
  const { route, order } = line.match
  if (!line.writeback_enabled || route === 'inbound_only') return '只入库'
  if (route === 'cross') return '跨生产备货单分配'
  return order ? orderLabel(order) : ''
}

export function groupLines(lines) {
  const groups = new Map()
  for (const line of lines) {
    const key = line.match.order_ref || '未填写单号'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(line)
  }
  return [...groups].map(([ref, items]) => ({ ref, items }))
}
