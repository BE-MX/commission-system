import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'

import { createCustomerMediaPreviewPayload } from '../src/views/design/customer-media/customerMediaPreviewPayload.js'

test('draft preview payload can be posted when batch and dimensions are Vue reactive', () => {
  const batch = reactive({
    id: 8, customer_id: 'C001', customer_name: 'Test Client', status: 'draft',
    assets: [{ id: 501, file_name: 'front.png', media_type: 'image', file_size: 120,
      content_url: '/api/customer-media/assets/501/content?expires=100&token=demo',
      tags: [{ dimension_id: 4, tag_value_id: 401, dimension_label: 'Color names', value: 'Ash' }] }],
  })
  const dimensions = reactive([{ id: 4, name: 'color_names', label: 'Color names', values: [] }])
  const payload = createCustomerMediaPreviewPayload(batch, dimensions)

  assert.doesNotThrow(() => structuredClone(payload))
  assert.equal(payload.type, 'customer-media-preview')
  assert.equal(payload.customer.customer_name, 'Test Client')
  assert.equal(payload.batch.assets[0].tags[0].value, 'Ash')
  assert.equal(payload.dimensions[0].name, 'color_names')
  assert.equal(payload.batch.status, undefined)
})
