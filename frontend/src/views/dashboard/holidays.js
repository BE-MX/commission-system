/**
 * 关键国家节假日引擎 — 工作台「节假日日历」与工作台 AI 问候上下文的数据源。
 *
 * 纯计算、零依赖、零网络：固定日期 + 复活节偏移 + 第N个星期几 + 日本节气近似公式
 * + 农历查表（2025-2027，表外年份自动省略该节日）。
 * 口径说明：按节日当天计，不做「周末顺延(observed)」平移——业务上关心的是客户那天不上班。
 *
 * 规则类型：
 *   { t:'fixed',  m, d }              固定月日
 *   { t:'easter', offset }            相对复活节星期日的偏移天数
 *   { t:'nth',    m, w, n }           m 月第 n 个星期 w（n=-1 为最后一个；w: 0=周日）
 *   { t:'equinox', which }            日本春分/秋分近似公式（1980-2099 有效）
 *   { t:'table',  dates:{YYYY:'MM-DD'} }  农历等无规律日期查表
 */

// 复活节星期日（Anonymous Gregorian algorithm）
export function easterSunday(year) {
  const a = year % 19
  const b = Math.floor(year / 100)
  const c = year % 100
  const d = Math.floor(b / 4)
  const e = b % 4
  const f = Math.floor((b + 8) / 25)
  const g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30
  const i = Math.floor(c / 4)
  const k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7
  const mm = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * mm + 114) / 31)
  const day = ((h + l - 7 * mm + 114) % 31) + 1
  return new Date(year, month - 1, day)
}

function nthWeekday(year, m, w, n) {
  if (n === -1) {
    const last = new Date(year, m, 0) // m 月最后一天（Date 的 day=0 回退）
    const diff = (last.getDay() - w + 7) % 7
    return new Date(year, m - 1, last.getDate() - diff)
  }
  const first = new Date(year, m - 1, 1)
  const diff = (w - first.getDay() + 7) % 7
  return new Date(year, m - 1, 1 + diff + (n - 1) * 7)
}

// 维多利亚日：5 月 25 日前的最后一个周一
function victoriaDay(year) {
  const ref = new Date(year, 4, 25)
  const diff = (ref.getDay() - 1 + 7) % 7 || 7
  return new Date(year, 4, 25 - diff)
}

// 日本节气近似（1980-2099）
function equinoxDay(year, which) {
  const y = year - 1980
  const base = which === 'spring' ? 20.8431 : 23.2488
  return Math.floor(base + 0.242194 * y) - Math.floor(y / 4)
}

const CN_LUNAR = {
  spring: { name: '春节', dates: { 2025: '01-29', 2026: '02-17', 2027: '02-06' } },
  qingming: { name: '清明节', dates: { 2025: '04-04', 2026: '04-05', 2027: '04-05' } },
  dragonboat: { name: '端午节', dates: { 2025: '05-31', 2026: '06-19', 2027: '06-09' } },
  midautumn: { name: '中秋节', dates: { 2025: '10-06', 2026: '09-25', 2027: '09-15' } },
}

const KR_LUNAR = {
  seollal: { name: '春节', dates: { 2025: '01-29', 2026: '02-17', 2027: '02-06' } },
  buddha: { name: '佛诞日', dates: { 2025: '05-05', 2026: '05-24', 2027: '05-13' } },
  chuseok: { name: '中秋节', dates: { 2025: '10-06', 2026: '09-25', 2027: '09-15' } },
}

function tableRules(table) {
  return Object.values(table).map(item => ({ t: 'table', dates: item.dates, name: item.name }))
}

export const HOLIDAY_COUNTRIES = [
  {
    code: 'CN', country: '中国', flag: '🇨🇳',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'fixed', m: 5, d: 1, name: '劳动节' },
      { t: 'fixed', m: 10, d: 1, name: '国庆节' },
      ...tableRules(CN_LUNAR),
    ],
  },
  {
    code: 'US', country: '美国', flag: '🇺🇸',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'nth', m: 1, w: 1, n: 3, name: '马丁·路德·金日' },
      { t: 'nth', m: 2, w: 1, n: 3, name: '总统日' },
      { t: 'nth', m: 5, w: 1, n: -1, name: '阵亡将士纪念日' },
      { t: 'fixed', m: 6, d: 19, name: '六月节' },
      { t: 'fixed', m: 7, d: 4, name: '独立日' },
      { t: 'nth', m: 9, w: 1, n: 1, name: '劳动节' },
      { t: 'nth', m: 10, w: 1, n: 2, name: '哥伦布日' },
      { t: 'fixed', m: 11, d: 11, name: '退伍军人节' },
      { t: 'nth', m: 11, w: 4, n: 4, name: '感恩节' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
    ],
  },
  {
    code: 'GB', country: '英国', flag: '🇬🇧',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'nth', m: 5, w: 1, n: 1, name: '五月初银行假' },
      { t: 'nth', m: 5, w: 1, n: -1, name: '春季银行假' },
      { t: 'nth', m: 8, w: 1, n: -1, name: '夏季银行假' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '节礼日' },
    ],
  },
  {
    code: 'DE', country: '德国', flag: '🇩🇪',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'fixed', m: 5, d: 1, name: '劳动节' },
      { t: 'easter', offset: 39, name: '耶稣升天日' },
      { t: 'easter', offset: 50, name: '圣灵降临节周一' },
      { t: 'fixed', m: 10, d: 3, name: '德国统一日' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '圣诞节次日' },
    ],
  },
  {
    code: 'FR', country: '法国', flag: '🇫🇷',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'fixed', m: 5, d: 1, name: '劳动节' },
      { t: 'fixed', m: 5, d: 8, name: '二战胜利日' },
      { t: 'easter', offset: 39, name: '耶稣升天日' },
      { t: 'easter', offset: 50, name: '圣灵降临节周一' },
      { t: 'fixed', m: 7, d: 14, name: '国庆日' },
      { t: 'fixed', m: 8, d: 15, name: '圣母升天节' },
      { t: 'fixed', m: 11, d: 1, name: '诸圣节' },
      { t: 'fixed', m: 11, d: 11, name: '一战停战日' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
    ],
  },
  {
    code: 'IT', country: '意大利', flag: '🇮🇹',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'fixed', m: 1, d: 6, name: '主显节' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'fixed', m: 4, d: 25, name: '解放日' },
      { t: 'fixed', m: 5, d: 1, name: '劳动节' },
      { t: 'fixed', m: 6, d: 2, name: '共和国日' },
      { t: 'fixed', m: 8, d: 15, name: '八月节' },
      { t: 'fixed', m: 11, d: 1, name: '诸圣节' },
      { t: 'fixed', m: 12, d: 8, name: '圣母无染原罪节' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '圣斯德望日' },
    ],
  },
  {
    code: 'ES', country: '西班牙', flag: '🇪🇸',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'fixed', m: 1, d: 6, name: '三王节' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'fixed', m: 5, d: 1, name: '劳动节' },
      { t: 'fixed', m: 8, d: 15, name: '圣母升天节' },
      { t: 'fixed', m: 10, d: 12, name: '国庆日' },
      { t: 'fixed', m: 11, d: 1, name: '诸圣节' },
      { t: 'fixed', m: 12, d: 6, name: '宪法日' },
      { t: 'fixed', m: 12, d: 8, name: '圣母无染原罪节' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
    ],
  },
  {
    code: 'NL', country: '荷兰', flag: '🇳🇱',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'fixed', m: 4, d: 27, name: '国王日' },
      { t: 'fixed', m: 5, d: 5, name: '解放日' },
      { t: 'easter', offset: 39, name: '耶稣升天日' },
      { t: 'easter', offset: 50, name: '圣灵降临节周一' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '节礼日' },
    ],
  },
  {
    code: 'JP', country: '日本', flag: '🇯🇵',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'nth', m: 1, w: 1, n: 2, name: '成人之日' },
      { t: 'fixed', m: 2, d: 11, name: '建国纪念日' },
      { t: 'fixed', m: 2, d: 23, name: '天皇诞生日' },
      { t: 'equinox', which: 'spring', name: '春分之日' },
      { t: 'fixed', m: 4, d: 29, name: '昭和之日' },
      { t: 'fixed', m: 5, d: 3, name: '宪法纪念日' },
      { t: 'fixed', m: 5, d: 4, name: '绿之日' },
      { t: 'fixed', m: 5, d: 5, name: '儿童之日' },
      { t: 'nth', m: 7, w: 1, n: 3, name: '海之日' },
      { t: 'fixed', m: 8, d: 11, name: '山之日' },
      { t: 'nth', m: 9, w: 1, n: 3, name: '敬老之日' },
      { t: 'equinox', which: 'autumn', name: '秋分之日' },
      { t: 'nth', m: 10, w: 1, n: 2, name: '体育之日' },
      { t: 'fixed', m: 11, d: 3, name: '文化之日' },
      { t: 'fixed', m: 11, d: 23, name: '勤劳感谢日' },
    ],
  },
  {
    code: 'KR', country: '韩国', flag: '🇰🇷',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'fixed', m: 3, d: 1, name: '三一节' },
      { t: 'fixed', m: 5, d: 5, name: '儿童节' },
      { t: 'fixed', m: 6, d: 6, name: '显忠日' },
      { t: 'fixed', m: 8, d: 15, name: '光复节' },
      { t: 'fixed', m: 10, d: 3, name: '开天节' },
      { t: 'fixed', m: 10, d: 9, name: '韩文日' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      ...tableRules(KR_LUNAR),
    ],
  },
  {
    code: 'AU', country: '澳大利亚', flag: '🇦🇺',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'fixed', m: 1, d: 26, name: '澳大利亚日' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'easter', offset: 1, name: '复活节周一' },
      { t: 'fixed', m: 4, d: 25, name: '澳新军团日' },
      { t: 'nth', m: 6, w: 1, n: 2, name: '国王诞辰' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '节礼日' },
    ],
  },
  {
    code: 'CA', country: '加拿大', flag: '🇨🇦',
    rules: [
      { t: 'fixed', m: 1, d: 1, name: '元旦' },
      { t: 'easter', offset: -2, name: '耶稣受难日' },
      { t: 'victoria', name: '维多利亚日' },
      { t: 'fixed', m: 7, d: 1, name: '加拿大日' },
      { t: 'nth', m: 9, w: 1, n: 1, name: '劳动节' },
      { t: 'nth', m: 10, w: 1, n: 2, name: '感恩节' },
      { t: 'fixed', m: 11, d: 11, name: '国殇纪念日' },
      { t: 'fixed', m: 12, d: 25, name: '圣诞节' },
      { t: 'fixed', m: 12, d: 26, name: '节礼日' },
    ],
  },
]

function toISODate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function ruleToDate(year, rule) {
  switch (rule.t) {
    case 'fixed':
      return new Date(year, rule.m - 1, rule.d)
    case 'easter': {
      const easter = easterSunday(year)
      return new Date(easter.getFullYear(), easter.getMonth(), easter.getDate() + rule.offset)
    }
    case 'nth':
      return nthWeekday(year, rule.m, rule.w, rule.n)
    case 'equinox':
      return new Date(year, rule.which === 'spring' ? 2 : 8, equinoxDay(year, rule.which))
    case 'victoria':
      return victoriaDay(year)
    case 'table': {
      const md = rule.dates[year]
      if (!md) return null
      const [m, d] = md.split('-').map(Number)
      return new Date(year, m - 1, d)
    }
    default:
      return null
  }
}

/** 某年的全部节假日（跨年份规则已在 ruleToDate 内归一到目标年） */
export function holidaysForYear(year) {
  const out = []
  for (const c of HOLIDAY_COUNTRIES) {
    for (const rule of c.rules) {
      const date = ruleToDate(year, rule)
      if (!date) continue
      out.push({
        date: toISODate(date),
        code: c.code,
        country: c.country,
        flag: c.flag,
        name: rule.name,
      })
    }
  }
  return out
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/** 今天（或指定日）哪些国家在放假 */
export function getTodayHolidays(from = new Date()) {
  const iso = toISODate(from)
  return holidaysForYear(from.getFullYear()).filter(h => h.date === iso)
}

/**
 * 未来 days 天内的节假日（含今天），按日期升序，附带 daysUntil。
 * perCountry>0 时每个国家最多保留 perCountry 条最近的（工作台卡片防刷屏）。
 */
export function getUpcomingHolidays({ from = new Date(), days = 60, perCountry = 0 } = {}) {
  const fromDay = startOfDay(from)
  const toDay = new Date(fromDay.getFullYear(), fromDay.getMonth(), fromDay.getDate() + days)
  const years = [fromDay.getFullYear(), toDay.getFullYear()]
  const all = years.flatMap(holidaysForYear)
  const seen = new Set()
  const list = all
    .filter(h => {
      const d = startOfDay(new Date(`${h.date}T00:00:00`))
      return d >= fromDay && d <= toDay
    })
    .map(h => ({
      ...h,
      daysUntil: Math.round((startOfDay(new Date(`${h.date}T00:00:00`)) - fromDay) / 86400000),
    }))
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.code.localeCompare(b.code)))
    .filter(h => {
      const key = `${h.date}:${h.code}:${h.name}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  if (perCountry > 0) {
    const count = {}
    return list.filter(h => {
      count[h.code] = (count[h.code] || 0) + 1
      return count[h.code] <= perCountry
    })
  }
  return list
}
