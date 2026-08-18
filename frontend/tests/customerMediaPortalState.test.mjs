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

test('portal display helpers keep status, initials and signed downloads stable', () => {
  assert.deepEqual(portalStatusMeta('in_review'), { label: '审核中', tone: 'in-review' })
  assert.deepEqual(portalStatusMeta('unexpected'), { label: '暂无素材', tone: 'empty' })
  assert.equal(initials('Lumière Hair Co.'), 'LC')
  assert.equal(initials('莱莎'), '莱莎')
  assert.equal(appendDownload('/content/1?expires=1&token=abc'), '/content/1?expires=1&token=abc&download=true')
})
