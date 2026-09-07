import { computed, ref } from 'vue'

// Inject the API so refresh races and network failures can be tested without a browser.
export function usePromptVersions(fetchOptions) {
  const promptVersions = ref([])
  const promptVersionId = ref(null)
  const promptVersionsLoading = ref(false)
  const promptVersionsError = ref('')
  let generation = 0
  const promptVersionReady = computed(() => !promptVersionsLoading.value && !promptVersionsError.value &&
    promptVersions.value.some(v => v.id === promptVersionId.value))

  async function loadPromptVersions() {
    const current = ++generation
    promptVersionsLoading.value = true
    promptVersionsError.value = ''
    try {
      const response = await fetchOptions()
      if (current !== generation) return
      promptVersions.value = response.data || []
      if (!promptVersions.value.some(v => v.id === promptVersionId.value)) {
        promptVersionId.value = promptVersions.value.find(v => v.is_default)?.id ?? promptVersions.value[0]?.id ?? null
      }
      if (!promptVersions.value.length) promptVersionsError.value = '暂无可用风格，请联系顾问'
    } catch {
      if (current === generation) promptVersionsError.value = '风格加载失败，请点击刷新重试'
    } finally {
      if (current === generation) promptVersionsLoading.value = false
    }
  }

  function resetPromptVersions() {
    generation++
    promptVersions.value = []
    promptVersionId.value = null
    promptVersionsLoading.value = false
    promptVersionsError.value = ''
  }
  return { promptVersions, promptVersionId, promptVersionsLoading, promptVersionsError,
    promptVersionReady, loadPromptVersions, resetPromptVersions }
}
