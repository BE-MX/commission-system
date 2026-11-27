/**
 * AI 预设管理三层面包屑筛选（功能 × 提供商 × 模型）与 URL query 同步。
 */
import { computed, ref, watch } from 'vue'

export const UNASSIGNED_FEATURE_KEY = '__unassigned__'

function parseCsv(val) {
  if (!val) return []
  return String(val).split(',').map(s => s.trim()).filter(Boolean)
}

export function usePresetFilters(presetsRef, featureCatalogRef, { route, router, activeTab } = {}) {
  const selectedFeatures = ref(new Set())
  const selectedProviders = ref(new Set())
  const selectedModels = ref(new Set())
  const search = ref('')

  function initFromRoute() {
    if (!route?.query) return
    selectedFeatures.value = new Set(parseCsv(route.query.feature))
    selectedProviders.value = new Set(parseCsv(route.query.provider))
    selectedModels.value = new Set(parseCsv(route.query.model))
    if (route.query.preset_q) search.value = String(route.query.preset_q)
  }
  initFromRoute()

  function syncToRoute() {
    if (!router || !route) return
    const next = { ...route.query }
    if (selectedFeatures.value.size) next.feature = [...selectedFeatures.value].join(',')
    else delete next.feature
    if (selectedProviders.value.size) next.provider = [...selectedProviders.value].join(',')
    else delete next.provider
    if (selectedModels.value.size) next.model = [...selectedModels.value].join(',')
    else delete next.model
    if (search.value.trim()) next.preset_q = search.value.trim()
    else delete next.preset_q
    if (activeTab?.value) next.tab = activeTab.value
    router.replace({ query: next }).catch(() => {})
  }

  function featureKeyOf(preset) {
    return preset.feature_key || UNASSIGNED_FEATURE_KEY
  }

  function matchesExcept(preset, skip) {
    const q = search.value.trim().toLowerCase()
    if (q) {
      const hit = (preset.preset_name || '').toLowerCase().includes(q)
        || (preset.description || '').toLowerCase().includes(q)
        || (preset.model || '').toLowerCase().includes(q)
      if (!hit) return false
    }
    if (skip !== 'feature' && selectedFeatures.value.size && !selectedFeatures.value.has(featureKeyOf(preset))) return false
    if (skip !== 'provider' && selectedProviders.value.size && !selectedProviders.value.has(String(preset.provider_id))) return false
    if (skip !== 'model' && selectedModels.value.size && !selectedModels.value.has(preset.model || '')) return false
    return true
  }

  const featureMetaMap = computed(() => {
    const map = new Map()
    for (const item of featureCatalogRef.value || []) {
      map.set(item.key, item)
    }
    map.set(UNASSIGNED_FEATURE_KEY, {
      key: UNASSIGNED_FEATURE_KEY,
      label: '未归属',
      nav_group: '待处理',
      route_path: null,
    })
    return map
  })

  const featureChips = computed(() => {
    const presets = presetsRef.value || []
    const orderKeys = [
      ...(featureCatalogRef.value || []).map(f => f.key),
      UNASSIGNED_FEATURE_KEY,
    ]
    return orderKeys
      .map(key => {
        const meta = featureMetaMap.value.get(key)
        const count = presets.filter(p => featureKeyOf(p) === key && matchesExcept(p, 'feature')).length
        return { value: key, label: meta?.label || key, count, isUnassigned: key === UNASSIGNED_FEATURE_KEY }
      })
      .filter(item => item.count > 0 || selectedFeatures.value.has(item.value))
  })

  const providerChips = computed(() => {
    const presets = presetsRef.value || []
    const seen = new Map()
    for (const p of presets) {
      if (!seen.has(p.provider_id)) seen.set(p.provider_id, p.provider_name || `#${p.provider_id}`)
    }
    return [...seen.entries()]
      .map(([id, label]) => {
        const key = String(id)
        const count = presets.filter(p => String(p.provider_id) === key && matchesExcept(p, 'provider')).length
        return { value: key, label, count }
      })
      .filter(item => item.count > 0 || selectedProviders.value.has(item.value))
  })

  const modelChips = computed(() => {
    const presets = presetsRef.value || []
    const eligible = presets.filter(p => matchesExcept(p, 'model') && p.model)
    const counts = new Map()
    for (const p of eligible) {
      counts.set(p.model, (counts.get(p.model) || 0) + 1)
    }
    for (const sel of selectedModels.value) {
      if (!counts.has(sel)) counts.set(sel, 0)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([model, count]) => ({ value: model, label: model, count }))
  })

  const filteredPresets = computed(() => (presetsRef.value || []).filter(p => matchesExcept(p, null)))

  const unassignedCount = computed(() => (presetsRef.value || []).filter(p => !p.feature_key).length)

  const groupedPresets = computed(() => {
    const groups = new Map()
    for (const p of filteredPresets.value) {
      const key = featureKeyOf(p)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(p)
    }
    const order = [
      ...(featureCatalogRef.value || []).map(f => f.key),
      UNASSIGNED_FEATURE_KEY,
    ]
    const extra = [...groups.keys()].filter(k => !order.includes(k))
    return [...order, ...extra]
      .filter(k => groups.has(k))
      .map(key => {
        const meta = featureMetaMap.value.get(key) || { key, label: key, nav_group: '其他', route_path: null }
        return {
          key,
          label: meta.label,
          navGroup: meta.nav_group,
          routePath: meta.route_path,
          isUnassigned: key === UNASSIGNED_FEATURE_KEY,
          items: groups.get(key),
        }
      })
  })

  function toggleChip(layer, value) {
    const target = layer === 'feature' ? selectedFeatures : (layer === 'provider' ? selectedProviders : selectedModels)
    const next = new Set(target.value)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    target.value = next
    // 功能或提供商变更后，自动剔除不在新交集中的模型选中态
    if (layer !== 'model' && selectedModels.value.size) {
      const validModels = new Set((presetsRef.value || []).filter(p => matchesExcept(p, 'model')).map(p => p.model))
      const pruned = new Set([...selectedModels.value].filter(m => validModels.has(m)))
      if (pruned.size !== selectedModels.value.size) selectedModels.value = pruned
    }
    syncToRoute()
  }

  function clearAll() {
    selectedFeatures.value = new Set()
    selectedProviders.value = new Set()
    selectedModels.value = new Set()
    search.value = ''
    syncToRoute()
  }

  function filterOnlyUnassigned() {
    selectedFeatures.value = new Set([UNASSIGNED_FEATURE_KEY])
    selectedProviders.value = new Set()
    selectedModels.value = new Set()
    syncToRoute()
  }

  const hasActiveFilters = computed(
    () => selectedFeatures.value.size > 0 || selectedProviders.value.size > 0 || selectedModels.value.size > 0 || Boolean(search.value.trim()),
  )

  watch(search, () => syncToRoute())

  return {
    selectedFeatures,
    selectedProviders,
    selectedModels,
    search,
    featureChips,
    providerChips,
    modelChips,
    filteredPresets,
    groupedPresets,
    unassignedCount,
    hasActiveFilters,
    toggleChip,
    clearAll,
    filterOnlyUnassigned,
  }
}
