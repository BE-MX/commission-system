import { computed, effectScope, onScopeDispose, ref, watch } from 'vue'
import * as icons from '@element-plus/icons-vue'
import { getEffectiveNavigationConfig } from '@/api/navigation'
import { MENU_GROUPS, NAV_ENTRIES } from '@/config/navigation'
import { accessibleNavigationSections } from '@/views/layout/navigationSearch'

const effective = ref(null)
const error = ref('')
let scope, consumers = 0
export const navigationDisplayConfig = effective

export function navigationRouteTitle(name, fallback) {
  const node = effective.value?.nodes?.find(item => item.id === name)
  return node?.titleSync && node.label ? node.label : fallback
}

export function useNavigationConfig(auth, commercePhase) {
  consumers++
  if (!scope) {
    scope = effectScope(true)
    scope.run(() => {
      let generation = 0, controller, pending = false
      async function refresh() {
        if (!auth.user?.id || pending) return
        const current = generation
        controller = new AbortController()
        pending = true
        try {
          const result = await getEffectiveNavigationConfig({ signal: controller.signal })
          if (current !== generation) return
          const payload = result.data
          if (!Array.isArray(payload?.nodes)) throw new Error('Invalid navigation configuration')
          effective.value = payload; error.value = ''
        } catch (cause) {
          if (current === generation) error.value = '导航配置暂未更新，正在使用上次有效配置'
        } finally { if (current === generation) pending = false }
      }
      watch(() => auth.user?.id, () => {
        generation++; controller?.abort(); pending = false
        effective.value = null; error.value = ''
        refresh()
      }, { immediate: true, flush: 'sync' })
      const foreground = () => { if (document.visibilityState === 'visible') refresh() }
      const interval = window.setInterval(foreground, 60000)
      window.addEventListener('focus', foreground)
      window.addEventListener('ark-navigation-updated', refresh)
      document.addEventListener('visibilitychange', foreground)
      onScopeDispose(() => {
        generation++; controller?.abort(); effective.value = null
        window.clearInterval(interval)
        window.removeEventListener('focus', foreground)
        window.removeEventListener('ark-navigation-updated', refresh)
        document.removeEventListener('visibilitychange', foreground)
      })
    })
  }
  onScopeDispose(() => { if (--consumers === 0) { scope.stop(); scope = null } })
  const sections = computed(() => accessibleNavigationSections(NAV_ENTRIES, MENU_GROUPS, auth,
    { commercePhase: commercePhase.value }, effective.value?.nodes, icons))
  return { sections, error, effective }
}
