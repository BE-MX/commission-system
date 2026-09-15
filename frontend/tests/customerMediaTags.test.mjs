import test from 'node:test'
import assert from 'node:assert/strict'
import {
  flattenSelection,
  groupTagsByDimension,
  selectionFromTags,
  unionTags,
} from '../src/views/design/customer-media/customerMediaTags.js'
import { webkitPathSegments } from '../src/views/design/customer-media/droppedFiles.js'

const dimensions = [
  { id: 1, label: '客户标签', name: 'customer_general', is_single_select: 0, values: [{ id: 11, value: '婚纱' }, { id: 12, value: '外景' }] },
  { id: 2, label: '色系', name: 'color', is_single_select: 1, values: [{ id: 21, value: '白' }, { id: 22, value: '黑' }] },
]

test('webkitRelativePath parses to folder segments without the file name', () => {
  assert.deepEqual(webkitPathSegments({ webkitRelativePath: '婚纱/外景/a.jpg' }), ['婚纱', '外景'])
  assert.deepEqual(webkitPathSegments({ webkitRelativePath: '婚纱/a.jpg' }), ['婚纱'])
  assert.deepEqual(webkitPathSegments({ name: 'a.jpg' }), [])
})

test('groupTagsByDimension emits the tags_json contract and dedupes values', () => {
  const grouped = groupTagsByDimension([
    { dimension_id: 1, tag_value_id: 11 },
    { dimension_id: 1, tag_value_id: 12 },
    { dimension_id: 1, tag_value_id: 11 },
    { dimension_id: 2, tag_value_id: 21 },
  ])
  assert.deepEqual(grouped, [
    { dimension_id: 1, tag_value_ids: [11, 12] },
    { dimension_id: 2, tag_value_ids: [21] },
  ])
})

test('unionTags merges folder/batch/per-file sources, dedupes and keeps single-select to one value', () => {
  const folder = [{ dimension_id: 2, tag_value_id: 21 }, { dimension_id: 1, tag_value_id: 11 }]
  const batch = [{ dimension_id: 2, tag_value_id: 22 }]
  const extra = [{ dimension_id: 1, tag_value_id: 11 }, { dimension_id: 1, tag_value_id: 12 }]
  const merged = unionTags([folder, batch, extra], dimensions)
  assert.deepEqual(merged.map(t => [t.dimension_id, t.tag_value_id]), [[2, 21], [1, 11], [1, 12]])
  assert.equal(merged.find(t => t.tag_value_id === 11).value, '婚纱')
  assert.equal(merged.find(t => t.tag_value_id === 11).dimension_label, '客户标签')
})

test('selection round-trip: tags -> picker selection -> flat tags with labels', () => {
  const selection = selectionFromTags([
    { dimension_id: 1, tag_value_id: 11 },
    { dimension_id: 1, tag_value_id: 12 },
    { dimension_id: 2, tag_value_id: 21 },
  ], dimensions)
  assert.deepEqual(selection, { 1: [11, 12], 2: 21 })
  const flat = flattenSelection(selection, dimensions)
  assert.deepEqual(flat, [
    { dimension_id: 1, dimension_label: '客户标签', tag_value_id: 11, value: '婚纱' },
    { dimension_id: 1, dimension_label: '客户标签', tag_value_id: 12, value: '外景' },
    { dimension_id: 2, dimension_label: '色系', tag_value_id: 21, value: '白' },
  ])
})
