import test from 'node:test'
import assert from 'node:assert/strict'
import {
  HOLIDAY_COUNTRIES,
  easterSunday,
  getTodayHolidays,
  getUpcomingHolidays,
  holidaysForYear,
} from '../src/views/dashboard/holidays.js'

function find(year, code, name) {
  return holidaysForYear(year).find(h => h.code === code && h.name === name)?.date
}

test('复活节算法：2025-2027 复活节星期日', () => {
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  assert.equal(iso(easterSunday(2025)), '2025-04-20')
  assert.equal(iso(easterSunday(2026)), '2026-04-05')
  assert.equal(iso(easterSunday(2027)), '2027-03-28')
})

test('美国：第N个星期几规则', () => {
  assert.equal(find(2026, 'US', '感恩节'), '2026-11-26') // 11月第4个周四
  assert.equal(find(2026, 'US', '阵亡将士纪念日'), '2026-05-25') // 5月最后周一
  assert.equal(find(2026, 'US', '劳动节'), '2026-09-07') // 9月第1个周一
  assert.equal(find(2026, 'US', '马丁·路德·金日'), '2026-01-19') // 1月第3个周一
})

test('复活节偏移：德国/英国 2026', () => {
  assert.equal(find(2026, 'DE', '耶稣受难日'), '2026-04-03')
  assert.equal(find(2026, 'DE', '复活节周一'), '2026-04-06')
  assert.equal(find(2026, 'DE', '耶稣升天日'), '2026-05-14')
  assert.equal(find(2026, 'DE', '圣灵降临节周一'), '2026-05-25')
  assert.equal(find(2026, 'GB', '夏季银行假'), '2026-08-31') // 8月最后周一
})

test('日本：节气公式与第N个周一', () => {
  assert.equal(find(2026, 'JP', '春分之日'), '2026-03-20')
  assert.equal(find(2026, 'JP', '秋分之日'), '2026-09-23')
  assert.equal(find(2026, 'JP', '成人之日'), '2026-01-12') // 1月第2个周一
  assert.equal(find(2026, 'JP', '海之日'), '2026-07-20') // 7月第3个周一
})

test('加拿大：维多利亚日（5/25 前最后一个周一）', () => {
  assert.equal(find(2026, 'CA', '维多利亚日'), '2026-05-18')
  assert.equal(find(2025, 'CA', '维多利亚日'), '2025-05-19')
})

test('农历查表：中国/韩国 2026', () => {
  assert.equal(find(2026, 'CN', '春节'), '2026-02-17')
  assert.equal(find(2026, 'CN', '端午节'), '2026-06-19')
  assert.equal(find(2026, 'CN', '中秋节'), '2026-09-25')
  assert.equal(find(2026, 'KR', '中秋节'), '2026-09-25')
  assert.equal(find(2027, 'CN', '春节'), '2027-02-06')
})

test('查表年份之外自动省略农历节日、固定节日仍在', () => {
  const list = holidaysForYear(2030)
  assert.equal(list.some(h => h.code === 'CN' && h.name === '春节'), false)
  assert.equal(list.some(h => h.code === 'CN' && h.name === '国庆节'), true)
})

test('getTodayHolidays / getUpcomingHolidays', () => {
  const today = getTodayHolidays(new Date(2026, 6, 4)) // 2026-07-04
  assert.equal(today.length, 1)
  assert.equal(today[0].code, 'US')

  const upcoming = getUpcomingHolidays({ from: new Date(2026, 11, 20), days: 20 })
  // 跨年窗口：12/25、12/26、1/1 都应命中
  assert.ok(upcoming.some(h => h.code === 'US' && h.date === '2026-12-25'))
  assert.ok(upcoming.some(h => h.code === 'CN' && h.date === '2027-01-01'))
  // daysUntil 单调不减且首条 ≥0
  assert.ok(upcoming.every(h => h.daysUntil >= 0))
  for (let i = 1; i < upcoming.length; i += 1) {
    assert.ok(upcoming[i].daysUntil >= upcoming[i - 1].daysUntil)
  }
  // perCountry 限流
  const capped = getUpcomingHolidays({ from: new Date(2026, 0, 1), days: 365, perCountry: 1 })
  const byCode = {}
  for (const h of capped) byCode[h.code] = (byCode[h.code] || 0) + 1
  assert.ok(Object.values(byCode).every(n => n === 1))
})

test('数据卫生：所有国家规则都能产出合法日期', () => {
  for (const c of HOLIDAY_COUNTRIES) {
    assert.ok(c.code && c.country && c.flag && c.rules.length > 0)
  }
  for (const h of holidaysForYear(2026)) {
    assert.match(h.date, /^2026-\d{2}-\d{2}$/)
    assert.ok(!Number.isNaN(new Date(`${h.date}T00:00:00`).getTime()))
  }
})
