import { computed } from 'vue'
import { useAsyncResource } from './useAsyncResource.js'

/** Append a cursor page only after its request succeeds; failed retries keep the same cursor. */
export function useCursorResource(fetchPage, { initialCursor = null, key = item => item.id } = {}) {
  const resource = useAsyncResource(async (scope, context) => {
    const previous = resource.data.value
    const page = await fetchPage(scope, previous.nextCursor, context)
    const items = new Map(previous.items.map(item => [key(item), item]))
    for (const item of page.items) items.set(key(item), item)
    return { items: [...items.values()], nextCursor: page.nextCursor, hasMore: page.hasMore }
  }, { initialData: { items: [], nextCursor: initialCursor, hasMore: true } })
  function load(scope) {
    if (resource.loading.value) return Promise.resolve(false)
    return resource.load(scope)
  }
  return {
    ...resource, load, items: computed(() => resource.data.value.items),
    hasData: computed(() => resource.data.value.items.length > 0),
    hasMore: computed(() => resource.data.value.hasMore),
    isEmpty: computed(() => resource.hasLoaded.value && !resource.loading.value && !resource.error.value && !resource.data.value.items.length),
  }
}
