import assert from 'node:assert/strict'
import test from 'node:test'
import { sortTableTree } from '../src/utils/tableSort.js'
import { groupedRows, roleField } from '../src/views/commission/commissionGrouping.js'

const ids = rows => rows.map(row => row.id)

test('tree sorting orders every sibling level and preserves parent links and source', () => {
  const tree = [
    { id: 1, value: 10, children: [
      { id: 11, value: 10, children: [{ id: 111, value: 100 }, { id: 112, value: 2 }] },
      { id: 12, value: 2 },
    ] },
    { id: 2, value: 2, children: [{ id: 21, value: 20 }, { id: 22, value: 3 }] },
  ]
  const snapshot = structuredClone(tree)
  const result = sortTableTree(tree, 'value', 'ascending')
  assert.deepEqual(ids(result), [2, 1])
  assert.deepEqual(ids(result[0].children), [22, 21])
  assert.deepEqual(ids(result[1].children), [12, 11])
  assert.deepEqual(ids(result[1].children[1].children), [112, 111])
  assert.notEqual(result[1], tree[0])
  assert.notEqual(result[1].children, tree[0].children)
  assert.deepEqual(tree, snapshot)
})

test('tree nulls stay last in both directions, ties remain stable and clear restores source order', () => {
  const children = Object.freeze([
    Object.freeze({ id: 3, value: null }), Object.freeze({ id: 2, value: '10.00' }),
    Object.freeze({ id: 1, value: '10' }), Object.freeze({ id: 4, value: '2.00' }),
  ])
  const tree = Object.freeze([Object.freeze({ id: 9, children })])
  assert.deepEqual(ids(sortTableTree(tree, 'value', 'ascending')[0].children), [4, 2, 1, 3])
  assert.deepEqual(ids(sortTableTree(tree, 'value', 'descending')[0].children), [2, 1, 4, 3])
  assert.deepEqual(ids(sortTableTree(tree, 'value', null)[0].children), [3, 2, 1, 4])
  assert.deepEqual(ids(tree[0].children), [3, 2, 1, 4])
})

test('tree reads full dates and natural text inside children', () => {
  const tree = [{ id: 1, children: [
    { id: 2, title: 'Task 10', due_date: '2027-01-01' },
    { id: 3, title: 'Task 2', due_date: '2026-12-31' },
    { id: 4, title: 'Task 20', due_date: null },
  ] }]
  assert.deepEqual(ids(sortTableTree(tree, 'title', 'ascending')[0].children), [3, 2, 4])
  assert.deepEqual(ids(sortTableTree(tree, 'due_date', 'descending')[0].children), [2, 3, 4])
})

test('commission trees retain month membership while sorting actual dynamic role decimals and group totals', () => {
  for (const role of ['salesperson', 'supervisor', 'second_supervisor']) {
    const field = roleField(role, 'commission')
    const rows = [
      { id: 1, collection_date: '2026-02-01', [field]: '100.00' },
      { id: 2, collection_date: '2026-01-01', [field]: '10.00' },
      { id: 3, collection_date: '2026-01-02', [field]: '2.00' },
      { id: 4, collection_date: '2026-02-02', [field]: '20.00' },
    ]
    const tree = groupedRows(rows, role)
    const read = row => row.isMonthGroup ? row.total_commission : row[field]
    const ascending = sortTableTree(tree, field, 'ascending', read)
    assert.deepEqual(ascending.map(row => row.month), ['2026-01', '2026-02'])
    assert.deepEqual(ascending.map(row => ids(row.children)), [[3, 2], [4, 1]])
    const descending = sortTableTree(tree, field, 'descending', read)
    assert.deepEqual(descending.map(row => row.month), ['2026-02', '2026-01'])
    assert.deepEqual(descending.map(row => ids(row.children)), [[1, 4], [2, 3]])
    assert.deepEqual(tree.map(row => ids(row.children)), [[2, 3], [1, 4]])
    assert.deepEqual(ids(rows), [1, 2, 3, 4])
  }
})
