import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { createMaterial as apiCreateMaterial, fetchMaterials } from '../api/index.js'
import { toast } from '../stores/toast.js'
import { CATEGORY_ORDER } from '../utils/labels.js'

export function useMaterials() {
  const route = useRoute()
  const materials = ref([])
  const loading = ref(true)
  const filters = ref({
    keyword: '',
    importance: route.query.importance || '',
    phase: route.query.phase ? Number(route.query.phase) : '',
    status: '',
  })

  async function load() {
    loading.value = true
    try {
      materials.value = (await fetchMaterials()) || []
    } finally {
      loading.value = false
    }
  }

  onMounted(load)

  const filtered = computed(() =>
    materials.value.filter((m) => {
      if (filters.value.importance && m.importance !== filters.value.importance) return false
      if (filters.value.phase && m.phase !== Number(filters.value.phase)) return false
      if (filters.value.status && m.status !== filters.value.status) return false
      if (filters.value.keyword) {
        const kw = filters.value.keyword.toLowerCase()
        if (!`${m.name} ${m.description || ''}`.toLowerCase().includes(kw)) return false
      }
      return true
    })
  )

  const grouped = computed(() => {
    const groups = []
    const byCat = new Map()
    for (const m of filtered.value) {
      if (!byCat.has(m.category)) byCat.set(m.category, [])
      byCat.get(m.category).push(m)
    }
    const cats = [...byCat.keys()].sort((a, b) => {
      const ia = CATEGORY_ORDER.indexOf(a)
      const ib = CATEGORY_ORDER.indexOf(b)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    })
    for (const cat of cats) {
      groups.push({ category: cat, items: byCat.get(cat) })
    }
    return groups
  })

  const summary = computed(() => ({
    total: materials.value.length,
    done: materials.value.filter((m) => ['submitted', 'confirmed', 'not_required'].includes(m.status)).length,
  }))

  async function create(payload) {
    await apiCreateMaterial(payload)
    toast.success('资料条目已新增')
    // 刷新失败不算新增失败——抛出去会让抽屉判定"需重试"
    try { await load() } catch { /* 拦截器已提示 */ }
  }

  return { materials, loading, filters, filtered, grouped, summary, load, create }
}
