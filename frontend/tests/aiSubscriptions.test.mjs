import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { usePresetFilters, UNASSIGNED_FEATURE_KEY } from '../src/views/system/composables/usePresetFilters.js'

test('usePresetFilters computes intersection counts, prunes orphaned models, and filters unassigned', () => {
  const presets = ref([
    { id: 1, preset_name: 'waybill_ocr', feature_key: 'tracking', provider_id: 1, provider_name: 'StepFun', model: 'step-3.7-flash', is_enabled: true },
    { id: 2, preset_name: 'tracking_summary', feature_key: 'tracking', provider_id: 2, provider_name: 'DeepSeek', model: 'deepseek-chat', is_enabled: true },
    { id: 3, preset_name: 'expo_wig_composite', feature_key: 'expo', provider_id: 3, provider_name: 'TeamRouter', model: 'gpt-image-2', is_enabled: true },
    { id: 4, preset_name: 'orphan_old', feature_key: null, provider_id: 2, provider_name: 'DeepSeek', model: 'deepseek-chat', is_enabled: false },
  ])
  const catalog = ref([
    { key: 'tracking', label: '物流跟踪', nav_group: '物流管理', route_path: '/tracking' },
    { key: 'expo', label: '展会营销', nav_group: '展会营销', route_path: '/expo/leads' },
  ])
  const replaced = []
  const route = { query: {} }
  const router = { replace: async q => { replaced.push(q.query); route.query = q.query } }

  const state = usePresetFilters(presets, catalog, { route, router, activeTab: ref('presets') })

  assert.equal(state.unassignedCount.value, 1)
  assert.equal(state.filteredPresets.value.length, 4)

  // 选择功能 tracking + 模型 deepseek-chat
  state.toggleChip('feature', 'tracking')
  assert.deepEqual(state.filteredPresets.value.map(p => p.id), [1, 2])
  state.toggleChip('model', 'deepseek-chat')
  assert.deepEqual(state.filteredPresets.value.map(p => p.id), [2])

  // 切换到提供商 StepFun 后，deepseek-chat 不在交集中应自动剔除
  state.toggleChip('provider', '1')
  assert.equal(state.selectedModels.value.size, 0)
  assert.deepEqual(state.filteredPresets.value.map(p => p.id), [1])

  // 一键只看未归属
  state.filterOnlyUnassigned()
  assert.deepEqual([...state.selectedFeatures.value], [UNASSIGNED_FEATURE_KEY])
  assert.deepEqual(state.filteredPresets.value.map(p => p.id), [4])

  // 清除全部筛选
  state.clearAll()
  assert.equal(state.filteredPresets.value.length, 4)
  assert.equal(state.hasActiveFilters.value, false)
  assert.ok(replaced.length >= 4)
})
