import { computed, reactive, ref, watch } from 'vue'
import { isNavigationFailure } from 'vue-router'
import {
  getAdjacentTab,
  getRouteTabKey,
  HOME_TAB,
  upsertRouteTab,
} from './navigationTabState'

export function useNavigationTabs(route, router) {
  const tabs = ref([{ ...HOME_TAB }])
  const cacheVersions = reactive({})

  const activeKey = computed(() => getRouteTabKey(route))

  watch(
    () => [getRouteTabKey(route), route.fullPath, route.meta?.title],
    () => {
      tabs.value = upsertRouteTab(tabs.value, route)
    },
    { immediate: true },
  )

  function selectTab(key) {
    const tab = tabs.value.find(item => item.key === key)
    if (tab && tab.key !== activeKey.value) router.push(tab.fullPath)
  }

  async function closeTab(key) {
    const tab = tabs.value.find(item => item.key === key)
    if (!tab?.closable) return

    const nextTab = getAdjacentTab(tabs.value, key)
    if (key === activeKey.value) {
      const failure = await router.push(nextTab?.fullPath || HOME_TAB.fullPath)
      if (isNavigationFailure(failure)) return
    }

    tabs.value = tabs.value.filter(item => item.key !== key)
    cacheVersions[key] = (cacheVersions[key] || 0) + 1
  }

  function getRouteCacheKey(viewRoute) {
    const key = getRouteTabKey(viewRoute)
    return `${key}:${cacheVersions[key] || 0}`
  }

  function getTabCacheName(key) {
    const source = `${key}:${cacheVersions[key] || 0}`
    let hash = 2166136261
    for (let index = 0; index < source.length; index += 1) {
      hash ^= source.charCodeAt(index)
      hash = Math.imul(hash, 16777619)
    }
    return `ArkTab_${(hash >>> 0).toString(36)}`
  }

  const cachedTabNames = computed(() => tabs.value.map(tab => getTabCacheName(tab.key)))

  return {
    tabs,
    activeKey,
    selectTab,
    closeTab,
    getRouteCacheKey,
    getTabCacheName,
    cachedTabNames,
  }
}
