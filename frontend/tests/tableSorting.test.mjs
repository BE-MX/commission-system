import assert from 'node:assert/strict'
import test from 'node:test'
import { compareTableValues, getSortValue, sortTableRows } from '../src/utils/tableSort.js'
import { SortableTableColumn } from '../src/components/SortableTableColumn.js'

test('local sorting compares numbers, natural text and dates without mutating source', () => {
  const rows = [{ id: 1, value: 100 }, { id: 2, value: 2 }, { id: 3, value: 20 }]
  assert.deepEqual(sortTableRows(rows, 'value', 'ascending').map(row => row.id), [2, 3, 1])
  assert.deepEqual(rows.map(row => row.id), [1, 2, 3])
  assert.ok(compareTableValues('订单2', '订单10') < 0)
  assert.ok(compareTableValues('2026-01-01', '2026-10-01') < 0)
  assert.ok(compareTableValues('1.15', '1.2') < 0)
  assert.ok(compareTableValues('9007199254740992', '9007199254740993') < 0)
  assert.ok(compareTableValues('-0.25', '-0.1') < 0)
  assert.equal(getSortValue({ user: { name: '亮哥' } }, 'user.name'), '亮哥')
})

test('empty values stay last in both directions; ties are stable and clear restores order', () => {
  const rows = [{ id: 1, value: null }, { id: 2, value: 2 }, { id: 3, value: 2 }, { id: 4, value: 0 }]
  assert.deepEqual(sortTableRows(rows, 'value', 'ascending').map(row => row.id), [4, 2, 3, 1])
  assert.deepEqual(sortTableRows(rows, 'value', 'descending').map(row => row.id), [2, 3, 4, 1])
  assert.deepEqual(sortTableRows(rows, 'value', null), rows)
})

test('default sorting is limited to data columns and preserves Element Plus registration', () => {
  const defaultSort = SortableTableColumn.props.sortable.default
  assert.equal(defaultSort({ prop: 'name' }), true)
  assert.equal(defaultSort({ property: 'price' }), true)
  for (const props of [{}, { type: 'selection', prop: 'id' }, { type: 'index' },
    { prop: 'id', className: 'table-action-column' }]) assert.equal(defaultSort(props), false)
  assert.equal(SortableTableColumn.name, 'ElTableColumn')
})
