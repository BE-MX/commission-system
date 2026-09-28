const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function calendarDate(value) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

function formatDate(value) {
  const year = value.getUTCFullYear()
  const month = String(value.getUTCMonth() + 1).padStart(2, '0')
  const day = String(value.getUTCDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function addDays(value, days) {
  const result = calendarDate(value)
  result.setUTCDate(result.getUTCDate() + days)
  return formatDate(result)
}

function mondayOf(value) {
  const weekday = calendarDate(value).getUTCDay()
  return addDays(value, -(weekday === 0 ? 6 : weekday - 1))
}

export function buildWeeklyHighs(history, today) {
  const currentMonday = mondayOf(today)
  const rows = (history || [])
    .filter(row => row.date < currentMonday && Number(row.rate) >= 1 && Number(row.rate) <= 20)
    .sort((left, right) => left.date.localeCompare(right.date))
  if (!rows.length) return null

  const latestDate = rows.at(-1).date
  const latestMonday = addDays(currentMonday, -7)
  const weeks = Array.from({ length: 4 }, (_, index) => {
    const start = addDays(latestMonday, (index - 3) * 7)
    const end = addDays(start, 6)
    const observations = rows.filter(row => row.date >= start && row.date <= end)
    if (!observations.length) return { start, end, high: null }

    const rate = Math.max(...observations.map(row => Number(row.rate)))
    const dates = observations.filter(row => Number(row.rate) === rate).map(row => row.date)
    const weekdays = dates.map(date => WEEKDAYS[calendarDate(date).getUTCDay()])
    return { start, end, high: { rate, dates, weekdays } }
  })

  return { latestDate, weeks }
}
