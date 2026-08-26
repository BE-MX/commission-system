import assert from 'node:assert/strict'
import test from 'node:test'

import {
  beijingCalendarDaysUntil,
  currentBeijingDate,
  formatBeijingDateTime,
  parseApiDateTime,
} from '../src/utils/datetime.js'


test('naive business datetime is interpreted as Beijing clock time', () => {
  const parsed = parseApiDateTime('2026-08-26T11:15:00')
  assert.equal(parsed.toISOString(), '2026-08-26T03:15:00.000Z')
  assert.equal(formatBeijingDateTime('2026-08-26T11:15:00'), '2026-08-26 11:15:00')
})


test('explicit UTC runtime datetime is displayed in Beijing time', () => {
  assert.equal(
    formatBeijingDateTime('2026-08-26T03:15:00', { naiveTimeZone: 'UTC' }),
    '2026-08-26 11:15:00',
  )
})


test('Beijing calendar day calculations do not depend on browser timezone', () => {
  assert.equal(beijingCalendarDaysUntil(currentBeijingDate()), 0)
  const beijingHalfPastMidnight = new Date('2026-08-25T16:30:00Z')
  assert.equal(currentBeijingDate(beijingHalfPastMidnight), '2026-08-26')
  assert.equal(beijingCalendarDaysUntil('2026-08-26', beijingHalfPastMidnight), 0)
  assert.equal(beijingCalendarDaysUntil('2026-08-27', beijingHalfPastMidnight), 1)
  assert.equal(parseApiDateTime('2026-08-26').toISOString(), '2026-08-25T16:00:00.000Z')
})
