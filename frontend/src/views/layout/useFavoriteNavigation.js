import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getNavigationPreferences, saveNavigationPreferences } from '@/api/navigation'
import { normalizeFavoriteKeys, resolveFavoriteItems, reorderFavoriteKeys } from './favoriteNavigationState'

export function useFavoriteNavigation(auth, available) {
  const keys = ref([]), loading = ref(false), saving = ref(false), error = ref(''), ready = ref(false)
  const items = computed(() => resolveFavoriteItems(keys.value, available.value))
  const locked = computed(() => loading.value || saving.value || !ready.value)
  let generation = 0, controller

  async function load() {
    const userId = auth.user?.id
    const current = ++generation
    controller?.abort()
    controller = new AbortController()
    keys.value = []; error.value = ''; ready.value = false; saving.value = false
    loading.value = Boolean(userId)
    if (!userId) return
    try {
      const result = await getNavigationPreferences({ signal: controller.signal })
      if (current !== generation) return
      keys.value = normalizeFavoriteKeys(result.data?.items)
      ready.value = true
    } catch (cause) {
      if (current === generation) error.value = '常用导航加载失败，请重试'
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function save(nextKeys) {
    if (locked.value || !auth.user?.id) return
    const current = generation
    saving.value = true; error.value = ''
    keys.value = normalizeFavoriteKeys(nextKeys)
    try {
      const result = await saveNavigationPreferences(keys.value, { signal: controller.signal })
      if (current === generation) keys.value = normalizeFavoriteKeys(result.data?.items)
    } catch (cause) {
      if (current !== generation) return
      // A timeout may already have committed. Read back before permitting another edit.
      try {
        const result = await getNavigationPreferences({ signal: controller.signal })
        if (current === generation) {
          keys.value = normalizeFavoriteKeys(result.data?.items)
          error.value = cause.response?.status === 403
            ? '当前导航权限已变更，请刷新页面后选择可访问的导航'
            : '保存请求未成功确认，已重新读取配置，请核对后再操作'
        }
      } catch (readError) {
        if (current === generation) {
          ready.value = false
          error.value = '保存状态待确认，请重试读取配置'
        }
      }
    } finally {
      if (current === generation) saving.value = false
    }
  }

  function toggle(name) {
    if (!available.value.some(item => item.name === name)) return
    return save(keys.value.includes(name) ? keys.value.filter(key => key !== name) : [...keys.value, name])
  }
  function reorder(orderedItems) {
    return save(reorderFavoriteKeys(keys.value, orderedItems.map(item => item.name)))
  }

  watch(() => auth.user?.id, load, { immediate: true, flush: 'sync' })
  onBeforeUnmount(() => { generation++; controller?.abort() })
  return { keys, items, loading, saving, locked, error, ready, load, toggle, reorder }
}
