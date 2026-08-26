const BEIJING_TIME_ZONE = 'Asia/Shanghai'

function hasExplicitTimezone(value) {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
}

/**
 * 解析后端时间。方舟业务 DATETIME 默认是无时区北京时间；
 * 明确的历史 UTC/跨机器字段传 { naiveTimeZone: 'UTC' }。
 */
export function parseApiDateTime(value, { naiveTimeZone = 'Asia/Shanghai' } = {}) {
  if (value == null || value === '') return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value

  const raw = String(value).trim()
  if (!raw) return null
  const normalized = raw.includes(' ') ? raw.replace(' ', 'T') : raw
  let instant = normalized
  if (!hasExplicitTimezone(normalized)) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) instant += 'T00:00:00'
    if (/^\d{4}-\d{2}-\d{2}T/.test(instant)) {
      instant += naiveTimeZone === 'UTC' ? 'Z' : '+08:00'
    }
  }
  const parsed = new Date(instant)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function partsOf(value, options) {
  const date = parseApiDateTime(value, options)
  if (!date) return null
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
  return Object.fromEntries(formatter.formatToParts(date).map(part => [part.type, part.value]))
}

export function formatBeijingDateTime(value, options = {}) {
  const parts = partsOf(value, options)
  if (!parts) return options.fallback ?? '-'
  const seconds = options.seconds === false ? '' : `:${parts.second}`
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}${seconds}`
}

export function formatBeijingShortDateTime(value, options = {}) {
  const parts = partsOf(value, options)
  if (!parts) return options.fallback ?? ''
  return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}

export function formatBeijingDate(value, options = {}) {
  const parts = partsOf(value, options)
  if (!parts) return options.fallback ?? '-'
  return `${parts.year}-${parts.month}-${parts.day}`
}

export function formatBeijingTime(value, options = {}) {
  const parts = partsOf(value, options)
  if (!parts) return options.fallback ?? ''
  const seconds = options.seconds === false ? '' : `:${parts.second}`
  return `${parts.hour}:${parts.minute}${seconds}`
}

export function currentBeijingHour() {
  return Number(new Intl.DateTimeFormat('en-GB', {
    timeZone: BEIJING_TIME_ZONE,
    hour: '2-digit',
    hourCycle: 'h23',
  }).format(new Date()))
}

export function currentBeijingDate(now = new Date()) {
  return formatBeijingDate(now)
}

export function currentBeijingDateTime({ seconds = true } = {}) {
  return formatBeijingDateTime(new Date(), { seconds }).replace(' ', 'T')
}

export function beijingStartOfToday(now = new Date()) {
  return new Date(`${currentBeijingDate(now)}T00:00:00+08:00`)
}

export function beijingCalendarDaysUntil(dateValue, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateValue || ''))) return null
  const target = new Date(`${dateValue}T00:00:00+08:00`)
  return Math.round((target.getTime() - beijingStartOfToday(now).getTime()) / 86400000)
}

/** 给日历/日期选择器使用：本地 Date 组件显示的年月日仍是北京日期。 */
export function beijingCalendarDate(dateValue = currentBeijingDate()) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateValue || ''))
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

export { BEIJING_TIME_ZONE }
