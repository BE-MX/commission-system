import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWeeklyHighs } from '../src/views/fx-settlement/weeklyHighs.js'
import { currentBeijingDate } from '../src/utils/datetime.js'

test('four consecutive Monday-to-Sunday weeks identify each published maximum and ties', () => {
  const today = currentBeijingDate(new Date('2026-09-27T16:30:00Z'))
  const result = buildWeeklyHighs([
    { date: '2026-08-31', rate: 6.7 },
    { date: '2026-09-02', rate: 6.9 },
    { date: '2026-09-04', rate: 6.9 },
    { date: '2026-09-07', rate: 6.8 },
    { date: '2026-09-11', rate: 6.75 },
    { date: '2026-09-15', rate: 6.85 },
    { date: '2026-09-21', rate: 6.88 },
    { date: '2026-09-23', rate: 6.92 },
    { date: '2026-09-24', rate: null },
    { date: '2026-09-29', rate: 7.1 },
  ], today)

  assert.equal(today, '2026-09-28')
  assert.equal(result.latestDate, '2026-09-23')
  assert.deepEqual(result.weeks.map(week => week.start), [
    '2026-08-31', '2026-09-07', '2026-09-14', '2026-09-21',
  ])
  assert.deepEqual(result.weeks.map(week => week.high?.rate), [6.9, 6.8, 6.85, 6.92])
  assert.deepEqual(result.weeks[0].high.weekdays, ['周三', '周五'])
  assert.deepEqual(result.weeks[3].high.dates, ['2026-09-23'])
})

test('missing published week remains empty instead of shifting or inventing a maximum', () => {
  const result = buildWeeklyHighs([
    { date: '2026-12-28', rate: 6.8 },
    { date: '2027-01-11', rate: 6.9 },
    { date: '2027-01-18', rate: 6.7 },
  ], '2027-01-25')
  assert.deepEqual(result.weeks.map(week => week.start), [
    '2026-12-28', '2027-01-04', '2027-01-11', '2027-01-18',
  ])
  assert.equal(result.weeks[1].high, null)
  assert.equal(result.weeks[3].high.weekdays[0], '周一')
})

test('September 25 week stays visible without inventing its unpublished FRED maximum', () => {
  const result = buildWeeklyHighs([
    { date: '2026-09-11', rate: 6.72 },
    { date: '2026-09-18', rate: 6.6975 },
  ], '2026-09-28')
  assert.equal(result.latestDate, '2026-09-18')
  assert.deepEqual(result.weeks.map(week => week.start), [
    '2026-08-31', '2026-09-07', '2026-09-14', '2026-09-21',
  ])
  assert.equal(result.weeks[3].end, '2026-09-27')
  assert.equal(result.weeks[3].high, null)
})

test('the ongoing Sunday week is excluded until it has ended', () => {
  const result = buildWeeklyHighs([
    { date: '2026-09-18', rate: 6.7 },
    { date: '2026-09-25', rate: 6.8 },
  ], '2026-09-27')
  assert.equal(result.latestDate, '2026-09-18')
  assert.equal(result.weeks.at(-1).end, '2026-09-20')
})

test('no history leaves the chart empty', () => {
  assert.equal(buildWeeklyHighs([], '2026-09-25'), null)
})
