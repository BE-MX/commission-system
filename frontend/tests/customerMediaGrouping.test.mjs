import test from 'node:test'
import assert from 'node:assert/strict'

import { filterMediaByTags, groupMediaByColorAndTexture, groupMediaByTags } from '../src/views/design/customer-media/customerMediaGrouping.js'

const dimensions = [
  { id: 1, name: 'customer_product_type', label: '产品类型' },
  { id: 2, name: 'shoot_style', label: '拍摄风格' },
  { id: 3, name: 'color_code', label: '色号' },
]
const product = (id, value) => ({ dimension_id: 1, tag_value_id: id, value, dimension_label: '产品类型' })
const style = (id, value) => ({ dimension_id: 2, tag_value_id: id, value, dimension_label: '拍摄风格' })
const color = (id, value) => ({ dimension_id: 3, tag_value_id: id, value, dimension_label: '色号' })
const assets = [
  { id: 11, tags: [product(101, '发帘'), style(201, '白底'), color(301, '#1')] },
  { id: 12, tags: [product(101, '发帘'), style(202, '场景'), color(301, '#1')] },
  { id: 13, tags: [product(102, '头套'), style(201, '白底'), color(302, '#2')] },
  { id: 14, tags: [style(201, '白底')] },
]

test('groups by product type and exposes only each group’s other dimension values', () => {
  const grouped = groupMediaByTags(assets, dimensions)
  assert.deepEqual(grouped.map(group => group.label), ['发帘', '头套', '未设置产品类型'])
  assert.deepEqual(grouped.map(group => group.assets.map(asset => asset.id)), [[11, 12], [13], [14]])
  assert.deepEqual(grouped[0].filters.map(filter => [filter.label, filter.values.map(value => value.value)]), [
    ['拍摄风格', ['白底', '场景']], ['色号', ['#1']],
  ])
  assert.deepEqual(grouped[1].filters[0].values.map(value => value.value), ['白底'])
  assert.equal(grouped[0].assets[0], assets[0])
})

test('stable customer product name keeps grouping after its display label changes', () => {
  const renamed = [{ ...dimensions[0], label: 'Product family' }, ...dimensions.slice(1)]
  const grouped = groupMediaByTags(assets, renamed)
  assert.deepEqual(grouped.map(group => group.label), ['发帘', '头套', '未设置产品类型'])
})

test('an image tagged with two products appears once in each product group', () => {
  const asset = { id: 15, tags: [product(101, '发帘'), product(102, '头套'), style(201, '白底')] }
  const grouped = groupMediaByTags([asset], dimensions)
  assert.deepEqual(grouped.map(group => group.assets.map(item => item.id)), [[15], [15]])
  assert.equal(grouped[0].assets[0], grouped[1].assets[0])
})

test('filter combines values within one dimension and intersects dimensions', () => {
  assert.deepEqual(filterMediaByTags(assets, [201, 202]).map(asset => asset.id), [11, 12, 13, 14])
  assert.deepEqual(filterMediaByTags(assets, [201, 301]).map(asset => asset.id), [11])
  assert.deepEqual(filterMediaByTags(assets, [999]).map(asset => asset.id), [])
})

test('workspace rows separate color names and textures type inside product groups', () => {
  const rowDimensions = [
    ...dimensions,
    { id: 4, name: 'color_names', label: 'Color names' },
    { id: 5, name: 'textures_type', label: 'Textures type' },
  ]
  const tag = (dimension_id, tag_value_id, value) => ({ dimension_id, tag_value_id, value })
  const images = [
    { id: 1, tags: [product(101, '发帘'), tag(4, 401, 'Ash'), tag(5, 501, 'Straight')] },
    { id: 2, tags: [product(101, '发帘'), tag(4, 401, 'Ash'), tag(5, 501, 'Straight')] },
    { id: 3, tags: [product(101, '发帘'), tag(4, 401, 'Ash'), tag(5, 502, 'Wavy')] },
    { id: 4, tags: [product(101, '发帘'), tag(4, 402, 'Brown'), tag(5, 501, 'Straight')] },
  ]
  const productGroup = groupMediaByTags(images, rowDimensions)[0]
  const rows = groupMediaByColorAndTexture(productGroup.assets, rowDimensions)
  assert.deepEqual(rows.map(row => [row.colorName, row.textureType, row.assets.map(asset => asset.id)]), [
    ['Ash', 'Straight', [1, 2]], ['Ash', 'Wavy', [3]], ['Brown', 'Straight', [4]],
  ])
})

test('missing color and texture labels leave the corresponding row headings empty', () => {
  const rowDimensions = [
    { id: 4, name: 'color_names', label: 'Color names' },
    { id: 5, name: 'textures_type', label: 'Textures type' },
  ]
  const images = [
    { id: 1, tags: [] },
    { id: 2, tags: [{ dimension_id: 4, tag_value_id: 401, value: 'Ash' }] },
    { id: 3, tags: [{ dimension_id: 5, tag_value_id: 501, value: 'Straight' }] },
  ]
  const rows = groupMediaByColorAndTexture(images, rowDimensions)
  assert.deepEqual(rows.map(row => [row.colorName, row.textureType]), [
    ['', ''], ['Ash', ''], ['', 'Straight'],
  ])
})
