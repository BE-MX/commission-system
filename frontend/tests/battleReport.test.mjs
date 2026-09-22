import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { addDays, errorText, money, rankPeople, targetChanges } from '../src/views/battle-report/helpers.js'

test('equal amounts keep roster order and consecutive ranks; incomplete data has no attainment rank', () => {
  const people = [
    { member_id: 1, gmv: '100', target: '100', progress_percent: 100, data_complete: true },
    { member_id: 2, gmv: '100', target: '100', progress_percent: 100, data_complete: true },
    { member_id: 3, gmv: '1000', progress_percent: null, data_complete: true },
    { member_id: 4, gmv: '20', progress_percent: 20, data_complete: false },
  ]
  assert.deepEqual(rankPeople(people, 'rate').map(p => p.rank), [1, 2, '—', '—'])
  assert.deepEqual(rankPeople(people, 'gmv').map(p => p.rank), [1, 2, 3, '—'])
})

test('completion ranking uses exact amounts even when displayed percentages tie', () => {
  const people = [{ member_id: 1, gmv: '1666', target: '10000', progress_percent: 16.7, data_complete: true },
    { member_id: 2, gmv: '1666.01', target: '10000', progress_percent: 16.7, data_complete: true }]
  assert.deepEqual(rankPeople(people, 'rate').map(p => p.member_id), [2, 1])
  const zeros = Array.from({ length: 22 }, (_, i) => ({ member_id: i + 1, gmv: '0', target: '100', progress_percent: 0, data_complete: true }))
  assert.deepEqual(rankPeople(zeros, 'rate').map(p => p.rank), Array.from({ length: 22 }, (_, i) => i + 1))
})

test('target changes preserve decimal strings, versions and only editable members', () => {
  const members = [{ id: 1, user_name: 'A', version: 4, target_usd: null, can_edit: true }, { id: 2, version: 1, target_usd: '10', can_edit: false }]
  assert.deepEqual(targetChanges(members, { 1: '100.01', 2: '999' }), [{ member_id: 1, version: 4, target_usd: '100.01' }])
  assert.deepEqual(targetChanges(members, { 1: '' }), [])
  for (const value of ['0', '-1', 'NaN', 'Infinity', '1.001', '1e6', '100000000000000']) assert.throws(() => targetChanges(members, { 1: value }))
})

test('calendar arithmetic preserves Beijing dates across midnight and leap dates', () => {
  assert.equal(addDays('2026-09-22', -7), '2026-09-15')
  assert.equal(addDays('2028-02-28', 1), '2028-02-29')
  assert.equal(addDays('2026-12-31', 1), '2027-01-01')
})

test('valid high-value goals preserve a one-cent edit and display precision', () => {
  const member = { id: 1, version: 2, can_edit: true, target_usd: '99999999999999.01' }
  assert.equal(targetChanges([member], { 1: '99999999999999.02' })[0].target_usd, '99999999999999.02')
  assert.equal(money('99999999999999.02'), '99,999,999,999,999.02')
  assert.deepEqual(targetChanges([{ ...member, target_usd: '10.00' }], { 1: '010' }), [])
})

test('structured validation errors remain readable', () => {
  assert.equal(errorText({ response: { data: { detail: [{ msg: '日期错误' }, { msg: '重复人员' }] } } }), '日期错误；重复人员')
})

test('date-picker calendar labels are not shifted in UTC+14 or western timezones', () => {
  const moduleUrl = new URL('../src/utils/datetime.js', import.meta.url).href
  for (const TZ of ['Pacific/Kiritimati', 'America/Los_Angeles', 'UTC']) {
    const output = execFileSync(process.execPath, ['--input-type=module', '-e', `import { formatCalendarDate } from ${JSON.stringify(moduleUrl)}; console.log(formatCalendarDate(new Date(2026, 8, 22)))`], { env: { ...process.env, TZ }, encoding: 'utf8' })
    assert.equal(output.trim(), '2026-09-22')
  }
})
