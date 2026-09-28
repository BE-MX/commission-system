import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMarketChartData } from '../src/views/fx-settlement/marketChartData.js'
import { currentBeijingDate } from '../src/utils/datetime.js'

const history = [
  { date: '2026-09-22', rate: 6.81 },
  { date: '2026-09-23', rate: 6.82 },
]

test('chart reaches Beijing today with a separately marked bank quote', () => {
  const today = currentBeijingDate(new Date('2026-09-24T16:30:00Z'))
  const data = buildMarketChartData({
    history,
    quote: { rate: 6.78, as_of: '2026-09-25T00:20:00' },
  }, today)
  assert.equal(today, '2026-09-25')
  assert.deepEqual(data.dates, ['2026-09-22', '2026-09-23', '2026-09-25'])
  assert.deepEqual(data.historyRates, [6.81, 6.82, null])
  assert.deepEqual(data.connectionRates, [null, 6.82, 6.78])
  assert.deepEqual(data.quoteRates, [null, null, 6.78])
  assert.equal(data.showQuote, true)
})

test('missing bank quote leaves today empty instead of inventing a rate', () => {
  const data = buildMarketChartData({ history, quote: null }, '2026-09-25')
  assert.equal(data.dates.at(-1), '2026-09-25')
  assert.deepEqual(data.historyRates, [6.81, 6.82, null])
  assert.deepEqual(data.quoteRates, [null, null, null])
  assert.equal(data.showQuote, false)
})

test('prior-day bank quote keeps its actual date and leaves today empty', () => {
  const data = buildMarketChartData({
    history,
    quote: { rate: 6.78, as_of: '2026-09-24T16:10:00+08:00' },
  }, '2026-09-25')
  assert.deepEqual(data.dates, ['2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25'])
  assert.deepEqual(data.quoteRates, [null, null, 6.78, null])
  assert.deepEqual(data.connectionRates, [null, 6.82, 6.78, null])
})

test('older quote never rewrites the later FRED point', () => {
  const data = buildMarketChartData({
    history,
    quote: { rate: 6.78, as_of: '2026-09-22T16:10:00' },
  }, '2026-09-25')
  assert.equal(data.showQuote, false)
  assert.deepEqual(data.quoteRates, [null, null, null])
})
