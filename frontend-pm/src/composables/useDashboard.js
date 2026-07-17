import { onMounted, ref } from 'vue'
import { fetchDashboard } from '../api/index.js'

export function useDashboard() {
  const data = ref(null)
  const loading = ref(true)

  async function load() {
    loading.value = true
    try {
      data.value = await fetchDashboard()
    } finally {
      loading.value = false
    }
  }

  onMounted(load)
  return { data, loading, reload: load }
}
