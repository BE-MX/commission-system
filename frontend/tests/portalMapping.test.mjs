import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mappingPayload, invalidEntries, sourceOptions } from '../src/views/portal/mappingDraft.mjs'
const sources = [{ item_id: 'one', model_key: 'M', color_key: 'C1', model_name: 'Standard', color_name: 'Black', length: '20in', weight: '20g', unit: 'pack' }, { item_id: 'two', model_key: 'M', color_key: 'C2', model_name: 'Standard', color_name: 'Brown', length: '22in', weight: '25g', unit: 'pack' }]
test('source options deduplicate stable model keys and distinguish individual SKUs', () => {
  assert.equal(sourceOptions(sources, 'model').length, 1)
  assert.equal(sourceOptions(sources, 'color').length, 2)
  assert.match(sourceOptions(sources, 'sku')[1].label, /22in.*25g.*pack.*two/)
})
test('withdrawn source remains explicit until operator removes it', () => {
  const entries = [{ kind: 'model', source_key: 'M', display_value: 'Alias' }, { kind: 'sku', source_key: 'withdrawn', display_value: 'Old' }]
  assert.deepEqual(invalidEntries(sources, entries).map(row => row.index), [1])
  assert.equal(entries.length, 2)
})
test('payload has only allowed mapping fields and exact stable SKU binding', () => {
  const body = mappingPayload(8, [{ kind: 'sku', source_key: 'one', item_id: 'wrong', display_value: 'Special', customer_sku: 'C-01', price: 5 }, { kind: 'color', source_key: 'C1', display_value: 'Midnight', customer_sku: 'ignored' }])
  assert.deepEqual(body, { base_version: 8, entries: [{ kind: 'sku', source_key: 'one', item_id: 'one', display_value: 'Special', customer_sku: 'C-01' }, { kind: 'color', source_key: 'C1', display_value: 'Midnight' }] })
})
