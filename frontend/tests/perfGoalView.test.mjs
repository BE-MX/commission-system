import test from 'node:test'
import assert from 'node:assert/strict'
import { canEditGoalPerson, isValidGoalInput, selectTeamGoalRows, teamGoalRowKey, perfViewAccess, selectedPerfRange, childGoalKey, teamGoalUpdate, splitPreviewByPerson } from '../src/views/perf-goal/viewState.js'

test('team metric selection keeps exact domain rows and never changes their values or identity', () => {
  const rows = [1, 2].flatMap(department_id => ['gmv', 'new_sign', 'repeat_customers', 'repeat_amount'].map((metric, i) => ({ department_id, metric, granularity: 'year', auto_value: i + 10 })))
  const selected = selectTeamGoalRows(rows, 'new_sign', 'year')
  assert.equal(selected.length, 2)
  assert.ok(selected.every(row => row.metric === 'new_sign' && row.auto_value === 11))
  assert.equal(new Set(rows.map(teamGoalRowKey)).size, rows.length)
  assert.equal(selectTeamGoalRows(rows, 'gmv', 'month').length, 0)
})
test('unlisted bound members can start targets; missing account IDs and invalid inputs cannot be saved', () => {
  assert.equal(canEditGoalPerson({ user_id: 7, listed: false }), true)
  for (const user_id of [null, undefined, '', 0]) assert.equal(canEditGoalPerson({ user_id }), false)
  for (const value of ['', ' ', '-1', 'NaN', 'Infinity', null]) assert.equal(isValidGoalInput(value), false)
  for (const value of ['0', 0, '1200.50']) assert.equal(isValidGoalInput(value), true)
})
test('displayed month/quarter/year range uses Beijing date strings, clips at cutoff and flags future periods', () => {
  assert.deepEqual(selectedPerfRange({ year: 2026, period_type: 'month', month: 9 }, '2026-10-29'), { range: ['2026-09-01', '2026-09-30'], notStarted: false })
  assert.deepEqual(selectedPerfRange({ year: 2026, period_type: 'quarter', quarter: 4 }, '2026-10-29'), { range: ['2026-10-01', '2026-10-29'], notStarted: false })
  assert.deepEqual(selectedPerfRange({ year: 2028, period_type: 'month', month: 2 }, '2028-03-01').range, ['2028-02-01', '2028-02-29'])
  assert.equal(selectedPerfRange({ year: 2026, period_type: 'month', month: 12 }, '2026-10-29').notStarted, true)
  assert.deepEqual(selectedPerfRange({ year: 2026 }, '2026-01-01').range, ['2026-01-01', '2026-01-01'])
})
test('salespeople start at self and team leaders retain only their allowed objects; unassigned bound users remain selectable', () => {
  const roster = { teams: [{ department_id: 10, captain_user_id: 1, name: 'A', members: [{ user_id: 1 }, { user_id: 2 }, { user_id: null }] }, { department_id: 20, captain_user_id: 3, name: 'B', members: [{ user_id: 3 }] }], unassigned: [{ user_id: 4 }] }
  const sales = perfViewAccess({ id: 2, roles: ['salesperson'] }, roster)
  assert.equal(sales.defaultScope, 'person'); assert.equal(sales.defaultId, 2); assert.equal(sales.compare, false)
  assert.deepEqual(sales.people.map(person => person.user_id), [2])
  const leader = perfViewAccess({ id: 1 }, roster)
  assert.equal(leader.defaultScope, 'team'); assert.deepEqual(leader.people.map(person => person.user_id), [1, 2])
  assert.deepEqual(leader.teams.map(team => team.department_id), [10])
  const admin = perfViewAccess({ id: 9, roles: ['supervisor'] }, roster)
  assert.equal(admin.company, true); assert.deepEqual(admin.people.map(person => person.user_id), [1, 2, 3, 4])
  assert.deepEqual(perfViewAccess(null, roster).people, [])
})

test('monthly keys carry their real quarter and match GET rows through PUT conversion', async () => {
  const { indexGoalRows, goalRowsFromEdits } = await import('../src/views/perf-goal/helpers.js')
  const row = { user_id: 7, metric: 'gmv', granularity: 'month', quarter: 2, month: 4, target_value: 101 }
  const key = childGoalKey(7, 'gmv', 'month', 4)
  assert.equal(indexGoalRows([row]).get(key), 101)
  assert.deepEqual(goalRowsFromEdits({ [key]: 102 })[0], { ...row, user_id: '7', target_value: 102 })
})
test('clear override is an explicit server command; untouched null does not clear a value', () => {
  const row = { department_id: 10, metric: 'gmv', granularity: 'year', factor: 1, override_value: 1800 }
  assert.equal(teamGoalUpdate(row, {}, { 10: '' }).clear_override, true)
  assert.equal(teamGoalUpdate(row, {}, { 10: '' }).override_value, null)
  assert.equal(teamGoalUpdate(row, { 10: '120' }, {}).factor, 1.2)
  assert.equal(teamGoalUpdate(row, {}, {}).clear_override, false)
  assert.equal(teamGoalUpdate(row, {}, {}).override_value, 1800)
})
test('quarter split preview merges one person across source quarters and aligns values by actual month', () => {
  const source = [{ user_id: 1, user_name: 'A', entries: [{ quarter: 1, month: 1, new_value: 10 }, { quarter: 1, month: 3, new_value: 30 }] }, { user_id: 1, user_name: 'A', entries: [{ quarter: 2, month: 4, new_value: 40 }] }]
  const rows = splitPreviewByPerson(source, 'month')
  assert.equal(rows.length, 1); assert.equal(rows[0].entries.length, 12)
  assert.equal(rows[0].entries[0].new_value, 10); assert.equal(rows[0].entries[2].new_value, 30)
  assert.equal(rows[0].entries[3].new_value, 40); assert.equal(rows[0].entries[1], null)
  assert.deepEqual(splitPreviewByPerson([], 'month'), [])
})
test('a multi-team captain never receives a second team beyond the backend first-team rule', () => {
  const roster = { teams: [{ department_id: 1, captain_user_id: 9, members: [{ user_id: 9 }] }, { department_id: 2, captain_user_id: 9, members: [{ user_id: 10 }] }] }
  const result = perfViewAccess({ id: 9 }, roster)
  assert.deepEqual(result.teams.map(team => team.department_id), [1]); assert.deepEqual(result.people.map(person => person.user_id), [9])
})
