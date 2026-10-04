import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTaskSort, sortTaskRows } from '../src/utils/taskTableSort.js'

const ids = rows => rows.map(row => row.id)

test('header cycles ascending, descending, clear and resets a new field', () => {
  const asc = nextTaskSort({ field: '', order: '' }, 'phase')
  assert.deepEqual(asc, { field: 'phase', order: 'asc' })
  const desc = nextTaskSort(asc, 'phase')
  assert.deepEqual(desc, { field: 'phase', order: 'desc' })
  assert.deepEqual(nextTaskSort(desc, 'phase'), { field: '', order: '' })
  assert.deepEqual(nextTaskSort(desc, 'title'), { field: 'title', order: 'asc' })
})

test('numbers compare numerically across the complete result with nulls last in either direction', () => {
  const tasks = [{ id: 5, phase: null }, { id: 3, phase: '10' }, { id: 2, phase: 2 }, { id: 1, phase: 2 }, { id: 4, phase: '' }]
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'phase', order: 'asc' })), [1, 2, 3, 4, 5])
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'phase', order: 'desc' })), [3, 1, 2, 4, 5])
  assert.deepEqual(ids(tasks), [5, 3, 2, 1, 4])
})

test('dates compare the full date and missing dates stay last', () => {
  const tasks = [{ id: 1, due_date: '2027-01-01' }, { id: 2, due_date: '2026-12-31' }, { id: 3 }]
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'due_date', order: 'asc' })), [2, 1, 3])
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'due_date', order: 'desc' })), [1, 2, 3])
})

test('text uses natural order, assignee names, displayed status labels and material names', () => {
  assert.deepEqual(ids(sortTaskRows([{ id: 1, title: 'Task 10' }, { id: 2, title: 'Task 2' }], { field: 'title', order: 'asc' })), [2, 1])
  const tasks = [{ id: 1, assignee: 'z', status: 'done', materials: [{ name: 'Zebra' }] }, { id: 2, assignee: 'a', status: 'blocked', materials: [{ name: 'Apple' }] }, { id: 3, materials: [] }]
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'assignee', order: 'asc' }, value => ({ z: 'Amy', a: 'Zoe' })[value])), [1, 2, 3])
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'status', order: 'asc' })), [2, 1, 3])
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'materials', order: 'desc' })), [1, 2, 3])
})

test('clear returns the existing result order without mutating row identities', () => {
  const tasks = [{ id: 9 }, { id: 2 }]
  const cleared = sortTaskRows(tasks, { field: '', order: '' })
  assert.notEqual(cleared, tasks)
  assert.deepEqual(ids(cleared), [9, 2])
  assert.equal(cleared[0], tasks[0])
  assert.deepEqual(ids(sortTaskRows(tasks, { field: 'unsafe', order: 'asc' })), [9, 2])
})
