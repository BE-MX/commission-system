import { readonly, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getTransitionStatus } from '@/api/commerceTransition'

// Platform-wide trading phase, shared by every navigation surface. null while
// unknown or unreadable: phase-gated (Ark-native) menus stay hidden then.
const phase = ref(null)
let loadedFor = null

async function load(userId) {
  try {
    const data = (await getTransitionStatus({ suppressToast: true })).data
    if (loadedFor === userId) phase.value = data?.phase ?? null
  } catch {
    if (loadedFor === userId) phase.value = null
  }
}

export function useCommercePhase() {
  const auth = useAuthStore()
  watch(() => auth.user?.id ?? null, userId => {
    if (userId === loadedFor) return
    loadedFor = userId
    phase.value = null
    if (userId !== null) load(userId)
  }, { immediate: true })
  return readonly(phase)
}
