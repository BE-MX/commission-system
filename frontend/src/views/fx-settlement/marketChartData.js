import { formatBeijingDate } from '../../utils/datetime.js'

export function buildMarketChartData(market, today) {
  const history = (market?.history || []).filter(row => row.date <= today).slice(-90)
  if (!history.length) return null

  const last = history.at(-1)
  const quote = market?.quote
  const quoteDay = quote?.as_of ? formatBeijingDate(quote.as_of, { fallback: '' }) : ''
  const showQuote = quoteDay >= last.date && quoteDay <= today
    && Number.isFinite(Number(quote?.rate)) && Number(quote.rate) >= 1 && Number(quote.rate) <= 20
  const dates = history.map(row => row.date)
  if (showQuote && quoteDay > last.date) dates.push(quoteDay)
  if (dates.at(-1) < today) dates.push(today)

  const historyRates = dates.map((_, index) => index < history.length ? history[index].rate : null)
  const quoteRates = dates.map(day => showQuote && day === quoteDay ? quote.rate : null)
  const connectionRates = dates.map(day => {
    if (!showQuote || quoteDay === last.date) return null
    return day === last.date ? last.rate : day === quoteDay ? quote.rate : null
  })

  return { dates, historyRates, quoteRates, connectionRates, showQuote }
}
