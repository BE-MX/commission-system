import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, ref } from 'vue'
import { useAssetTagFilters } from '../src/views/asset/composables/useAssetTagFilters.js'

test('asset tag filters keep parent cascade and clear selected descendants', () => {
  const dimensions = ref([
    { name: 'content_category', values: [{ id: 1, value: 'Product' }] },
    { name: 'content_type', values: [
      { id: 2, value: 'Wig', parent_value_id: 1 },
      { id: 3, value: 'Weft', parent_value_id: 9 },
    ] },
    { name: 'product_family', values: [
      { id: 4, value: 'Wefts' },
      { id: 5, value: 'Genius Weft', parent_value_id: 4 },
    ] },
  ])
  const activeFilters = reactive({ content_category: [1] })
  const filters = useAssetTagFilters({
    dimensions, filterKeyword: ref(''), activeFilters, assets: ref([]),
    availableTagIds: ref(new Set()), hasActiveTagFilter: ref(false),
  })

  assert.deepEqual(filters.filteredValues(dimensions.value[1]).map(value => value.id), [2])
  filters.toggleTag('product_family', 4, dimensions.value[2])
  assert.deepEqual(activeFilters.product_family, [4, 5])
  filters.toggleTag('product_family', 4, dimensions.value[2])
  assert.deepEqual(activeFilters.product_family, [])
})

test('selected tag style uses shared color tokens when no custom color is set', () => {
  const activeFilters = reactive({ theme: [7] })
  const filters = useAssetTagFilters({
    dimensions: ref([]), filterKeyword: ref(''), activeFilters, assets: ref([]),
    availableTagIds: ref(new Set()), hasActiveTagFilter: ref(false),
  })

  assert.deepEqual(filters.getTagStyle('theme', 7), {
    backgroundColor: 'var(--color-primary)',
    color: 'var(--card-bg)',
    borderColor: 'transparent',
  })
  assert.equal(filters.getTagStyle('theme', 8).backgroundColor, undefined)
})
