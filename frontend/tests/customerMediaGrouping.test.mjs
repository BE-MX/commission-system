import test from 'node:test'
import assert from 'node:assert/strict'

import { filterMediaByTags, groupMediaByTags } from '../src/views/design/customer-media/customerMediaGrouping.js'

const dimensions = [{ id: 1, label: '用途' }, { id: 2, label: '系列' }]
const assets = [
  { id: 11, tags: [{ dimension_id: 1, tag_value_id: 101, value: '白底图' }, { dimension_id: 2, tag_value_id: 201, value: '春季' }] },
  { id: 12, tags: [{ dimension_id: 1, tag_value_id: 102, value: '场景图' }, { dimension_id: 2, tag_value_id: 201, value: '春季' }] },
  { id: 13, tags: [{ dimension_id: 1, tag_value_id: 101, value: '白底图' }, { dimension_id: 2, tag_value_id: 202, value: '夏季' }] },
  { id: 14, tags: [] },
]

test('one file appears in each assigned dimension without creating a copy', () => {
  const grouped = groupMediaByTags(assets, dimensions)
  assert.deepEqual(grouped.map(group => group.label), ['用途', '系列', '未打标签'])
  assert.deepEqual(grouped[0].buckets.map(bucket => bucket.assets.map(asset => asset.id)), [[11, 13], [12]])
  assert.equal(grouped[0].buckets[0].assets[0], assets[0])
  assert.deepEqual(grouped[2].buckets[0].assets.map(asset => asset.id), [14])
})

test('filter combines values within one dimension and intersects dimensions', () => {
  assert.deepEqual(filterMediaByTags(assets, [101, 102]).map(asset => asset.id), [11, 12, 13])
  assert.deepEqual(filterMediaByTags(assets, [101, 201]).map(asset => asset.id), [11])
  assert.deepEqual(filterMediaByTags(assets, [999]).map(asset => asset.id), [])
})
