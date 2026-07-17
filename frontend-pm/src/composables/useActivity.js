import { onMounted, ref } from 'vue'
import { fetchActivity, fetchMembers } from '../api/index.js'

const PAGE = 50

export function useActivity() {
  const items = ref([])
  const total = ref(0)
  const loading = ref(false)
  const filters = ref({ username: '', object_type: '' })
  const members = ref([])

  async function load(append = false) {
    loading.value = true
    try {
      const data = await fetchActivity({
        username: filters.value.username || '',
        object_type: filters.value.object_type || '',
        limit: PAGE,
        offset: append ? items.value.length : 0,
      })
      total.value = data?.total || 0
      const list = data?.items || []
      items.value = append ? [...items.value, ...list] : list
    } finally {
      loading.value = false
    }
  }

  onMounted(async () => {
    load()
    try {
      members.value = (await fetchMembers()) || []
    } catch { /* 筛选器降级为不过滤，不阻断 */ }
  })

  const hasMore = () => items.value.length < total.value

  return { items, total, loading, filters, members, load, hasMore }
}
