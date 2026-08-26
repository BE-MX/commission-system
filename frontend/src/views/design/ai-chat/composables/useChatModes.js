import { computed, onMounted, ref } from 'vue'
import { getMode, getSessionMode, listModes } from '@/api/aiChat'

const dataOf = response => response?.data ?? response
const messageOf = error => error?.response?.data?.detail || error?.message || '文件加载失败，请重试或取消当前方式'

export function useChatModes({ messages, streaming, currentSessionId }) {
  const items = ref([])
  const selected = ref(null)
  const loading = ref(false)
  const error = ref('')
  const catalogError = ref('')
  const preview = ref(null)
  const previewLoading = ref(false)
  const previewError = ref('')
  const detailsOpen = ref(false)
  const locked = computed(() => messages.value.length > 0)
  let generation = 0

  async function loadCatalog() {
    catalogError.value = ''
    try { items.value = dataOf(await listModes()).items }
    catch (err) { catalogError.value = '对话方式暂时无法加载，可重试或直接聊天' }
  }

  function restore(mode = null) {
    generation += 1
    selected.value = mode
    preview.value = null
    loading.value = false
    error.value = ''
    detailsOpen.value = false
    previewLoading.value = false
    previewError.value = ''
  }

  async function select(mode, { force = false } = {}) {
    if (locked.value || streaming.value) return
    if (!mode) { restore(); return }
    if (!force && selected.value?.id === mode.id && !error.value) return
    const expected = ++generation
    selected.value = { ...mode, version: undefined }
    preview.value = null
    loading.value = true
    error.value = ''
    try {
      const detail = dataOf(await getMode(mode.id))
      if (expected !== generation) return
      const { content, ...metadata } = detail
      selected.value = metadata
      preview.value = detail
    } catch (err) {
      if (expected === generation) error.value = messageOf(err)
    } finally {
      if (expected === generation) loading.value = false
    }
  }

  async function showDetails() {
    detailsOpen.value = true
    if (preview.value || !selected.value) return
    const expected = generation
    previewLoading.value = true
    previewError.value = ''
    try {
      const detail = dataOf(await (locked.value
        ? getSessionMode(currentSessionId.value) : getMode(selected.value.id)))
      if (expected === generation) preview.value = detail
    } catch (err) {
      if (expected === generation) previewError.value = messageOf(err)
    } finally {
      if (expected === generation) previewLoading.value = false
    }
  }

  onMounted(loadCatalog)
  return { items, selected, loading, error, locked, catalogError, loadCatalog, select, restore,
    preview, previewLoading, previewError, detailsOpen, showDetails }
}
