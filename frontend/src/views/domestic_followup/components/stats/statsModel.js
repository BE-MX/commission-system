export const VIEW_OPTIONS = [
  { key: 'personal', label: '个人数据', icon: 'User' },
  { key: 'team', label: '团队数据', icon: 'UserFilled' },
  { key: 'ai', label: 'AI 建议', icon: 'MagicStick' },
]

export const CATEGORY_LABELS = {
  deal: '可能成交', cold: '正在变冷', rhythm: '节奏调整', method: '跟进方式',
  common: '共性问题', single: '个别问题', practice: '有效做法', frequency: '节奏建议',
}

export function availableViews(canReadAll) {
  return VIEW_OPTIONS.filter(option => canReadAll || option.key !== 'team')
}

export function nextView(current, canReadAll, direction) {
  const views = availableViews(canReadAll)
  const index = views.findIndex(item => item.key === current)
  return views[(index + direction + views.length) % views.length].key
}

export function percent(value, fallback = '—') {
  return value === null || value === undefined ? fallback : `${Math.round(Number(value) * 100)}%`
}

export function deltaInfo(current, previous, { percentagePoints = false, inverse = false } = {}) {
  if (current === null || current === undefined || previous === null || previous === undefined) return null
  if (percentagePoints) {
    const amount = Math.round((Number(current) - Number(previous)) * 100)
    return { text: `${amount > 0 ? '+' : ''}${amount} 个百分点`, direction: amount === 0 ? 'flat' : (amount > 0) !== inverse ? 'up' : 'down' }
  }
  if (Number(previous) === 0) {
    if (Number(current) === 0) return { text: '持平', direction: 'flat' }
    return { text: `新增 ${Math.abs(Number(current) - Number(previous))}`, direction: inverse ? 'down' : 'up' }
  }
  const amount = Math.round((Number(current) - Number(previous)) / Math.abs(Number(previous)) * 100)
  return { text: `${amount > 0 ? '+' : ''}${amount}%`, direction: amount === 0 ? 'flat' : (amount > 0) !== inverse ? 'up' : 'down' }
}

export function shortDate(value) {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(String(value || ''))
  return match ? `${Number(match[1])}/${Number(match[2])}` : '—'
}

export function weekday(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''))
  if (!match) return ''
  const day = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day]
}

export function heatLevel(value) {
  return value === 0 ? 0 : value <= 2 ? 1 : value <= 4 ? 2 : value <= 6 ? 3 : 4
}

export function recordsParams(period, extra = {}) {
  return { date_from: period?.start, date_to: period?.end, ...extra }
}

export function groupInsights(items, category) {
  return (items || []).filter(item => item.category === category)
}

export function qualityDescription(key) {
  return {
    next_step: '全部已确认跟进记录中，填了下次跟进日期的占比（不要求填写本次结果）',
    commitment: '已到期约定中，未顺延且按时完成的占比',
    effective_progress: '填了沟通结果的记录中，标记为有效推进的占比',
  }[key] || ''
}
