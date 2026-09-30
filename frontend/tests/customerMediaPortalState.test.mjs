import test from 'node:test'
import assert from 'node:assert/strict'

import {
  appendDownload,
  filterPreviewBatches,
  initials,
  portalStatusMeta,
} from '../src/views/design/customer-media/portalPreviewState.js'

const batches = [{
  id: 1,
  assets: [
    { id: 11, media_type: 'image', file_name: 'Front View.PNG' },
    { id: 12, media_type: 'video', file_name: 'Turnaround.mp4' },
  ],
}, {
  id: 2,
  assets: [{ id: 21, media_type: 'image', file_name: 'Detail.jpg' }],
}]

test('preview filters published batch assets without mutating the response', () => {
  const filtered = filterPreviewBatches(batches, { search: 'front', mediaType: 'image' })
  assert.deepEqual(filtered.map(batch => batch.assets.map(asset => asset.id)), [[11]])
  assert.equal(batches[0].assets.length, 2)
  assert.deepEqual(filterPreviewBatches(batches, { mediaType: 'video' }).map(batch => batch.id), [1])
})

test('preview combines product type with media and filename filters across batches', () => {
  const tag = (id, value) => ({ dimension_id: 3, tag_value_id: id, value, dimension_label: 'Product type' })
  const tagged = [
    { id: 1, assets: [
      { id: 11, media_type: 'image', file_name: 'Front Wig.png', tags: [tag(101, 'Wig')] },
      { id: 12, media_type: 'video', file_name: 'Front Cap.mp4', tags: [tag(102, 'Cap')] },
    ] },
    { id: 2, assets: [{ id: 21, media_type: 'image', file_name: 'Front Cap.png', tags: [tag(102, 'Cap')] }] },
  ]
  const result = filterPreviewBatches(tagged, {
    search: 'front', mediaType: 'image', productTypeIds: [102],
    tagDimensions: [{ id: 3, name: 'customer_product_type', label: 'Product type' }],
  })
  assert.deepEqual(result.map(batch => [batch.id, batch.assets.map(asset => asset.id)]), [[2, [21]]])
  assert.equal(tagged[0].assets.length, 2)
})

test('portal display helpers keep status, initials and signed downloads stable', () => {
  assert.deepEqual(portalStatusMeta('in_review'), { label: '审核中', tone: 'in-review' })
  assert.deepEqual(portalStatusMeta('unexpected'), { label: '暂无素材', tone: 'empty' })
  assert.equal(initials('Lumière Hair Co.'), 'LC')
  assert.equal(initials('莱莎'), '莱莎')
  assert.equal(appendDownload('/content/1?expires=1&token=abc'), '/content/1?expires=1&token=abc&download=true')
})
