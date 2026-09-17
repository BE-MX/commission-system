import test from 'node:test'
import assert from 'node:assert/strict'
import { validPayload, snapshotIsStale, screenUrl } from '../src/views/festival/september-screen-state.js'
import { currentBeijingDate } from '../src/utils/datetime.js'

function payload() {
  const groups = [21, 15, 11, 10, 14, 15, 22, 5].map((target, index) => ({
    name: `team${index}`, target, done: 0, rate: 0, remaining: target, excess: 0,
    members: index === 7 ? 1 : 2, solo: index === 7, first: false, achieved: false,
  }))
  return {
    period: { start: '2026-09-01', end: '2026-09-30' }, phase: 'ongoing',
    as_of: '2026-09-17T10:30:00+08:00', groups,
    total: { target: 113, done: 0, rate: 0, remaining: 113, excess: 0, achieved_groups: 0 },
    champion: { names: [], state: 'vacant', tied: false }, data_quality: { ok: true },
  }
}

test('zero is valid but a partial snapshot cannot replace good data', () => {
  const data = payload()
  assert(validPayload(data))
  assert(!validPayload({}))
  data.total.done = 1
  assert(!validPayload(data))
  data.total.done = 0
  data.groups.pop()
  assert(!validPayload(data))
})

test('invalid money-free counters and wrong month are rejected', () => {
  const data = payload()
  data.groups[0].rate = NaN
  assert(!validPayload(data))
  data.groups[0].rate = 0
  data.period.start = '2026-08-01'
  assert(!validPayload(data))
})

test('solo and below-target first flags are rejected', () => {
  const data = payload()
  data.champion.names = [data.groups[7].name]
  data.groups[7].first = true
  assert(!validPayload(data))
  data.groups[7].first = false
  data.champion.names = [data.groups[0].name]
  data.groups[0].first = true
  assert(!validPayload(data))
})

test('data issue accepts partial group facts but no complete total or champion', () => {
  const data = payload()
  data.data_quality.ok = false
  data.total.done = null
  assert(validPayload(data))
  data.total.done = 0
  assert(!validPayload(data))
})

test('staleness uses snapshot time with explicit Beijing offset', () => {
  const data = payload()
  assert(!snapshotIsStale(data, Date.parse('2026-09-17T02:34:59Z')))
  assert(snapshotIsStale(data, Date.parse('2026-09-17T02:35:01Z')))
  assert(snapshotIsStale(null))
})

test('Beijing date crosses midnight independent of browser local day', () => {
  assert.equal(currentBeijingDate(new Date('2026-09-30T15:59:59Z')), '2026-09-30')
  assert.equal(currentBeijingDate(new Date('2026-09-30T16:00:00Z')), '2026-10-01')
})

test('channel navigation keeps key and screen controls, drops unknown query', () => {
  const url = screenUrl('zhaiyao.html', '?key=local%2Bkey&stay=1&preview=1&source=ark&next=https://example.com')
  const parsed = new URL(url, 'http://localhost')
  assert.equal(parsed.pathname, '/festival/zhaiyao.html')
  assert.equal(parsed.searchParams.get('key'), 'local+key')
  assert.equal(parsed.searchParams.get('stay'), '1')
  assert.equal(parsed.searchParams.get('preview'), '1')
  assert(!parsed.searchParams.has('next'))
})
