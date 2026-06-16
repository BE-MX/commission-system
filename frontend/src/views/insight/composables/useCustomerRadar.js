import { ref, reactive, computed, onMounted } from 'vue'
import {
  getRadarFocus, getRadarThreadCounts,
  completeRadarAction, dismissRadarAction, snoozeRadarAction,
  submitRadarFeedback, getRadarProfile, getRadarSourceRecords,
  addRadarNote, refreshRadarActions,
} from '@/api/insight'

export function useCustomerRadar() {
  const loading = ref(false)
  const focusData = ref({ threads: [], summary: {} })
  const threadCounts = ref({})
  const selectedThread = ref(null)
  const selectedActionId = ref(null)
  const selectedAction = ref(null)
  const selectedProfile = ref(null)
  const profileLoading = ref(false)
  const sourceDrawerVisible = ref(false)
  const sourceRecords = ref([])
  const sourceTab = ref('all')
  const searchKeyword = ref('')

  // 展平所有行动（供搜索用）
  const allActions = computed(() => {
    const actions = []
    for (const thread of focusData.value.threads || []) {
      for (const action of thread.actions || []) {
        actions.push({ ...action, thread_label: thread.label, thread_color: thread.color })
      }
    }
    return actions
  })

  // 按选中线索过滤
  const filteredActions = computed(() => {
    let actions = allActions.value
    if (selectedThread.value) {
      actions = actions.filter(a => a.thread_group === selectedThread.value)
    }
    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      actions = actions.filter(a =>
        (a.customer_name || '').toLowerCase().includes(kw)
        || (a.action_reason || '').toLowerCase().includes(kw)
        || (a.customer_region || '').toLowerCase().includes(kw)
      )
    }
    return actions
  })

  // 线索导航列表
  const threadNav = computed(() => {
    const groups = [
      { group: 'all', label: '全部重点', desc: '今天值得先看的客户建议', count: allActions.value.length, color: 'gold', priority_label: '' },
    ]
    for (const thread of focusData.value.threads || []) {
      groups.push({
        group: thread.group,
        label: thread.label,
        desc: thread.desc,
        count: thread.count,
        color: thread.color,
        priority_label: thread.priority_label,
      })
    }
    return groups
  })

  async function loadFocus() {
    loading.value = true
    try {
      const res = await getRadarFocus()
      focusData.value = res.data?.data || { threads: [], summary: {} }
      // 同时加载线索计数
      const cntRes = await getRadarThreadCounts()
      threadCounts.value = cntRes.data?.data || {}
    } catch (e) {
      console.error('Failed to load radar focus:', e)
    } finally {
      loading.value = false
    }
  }

  async function selectThread(group) {
    selectedThread.value = group === 'all' ? null : group
    // 自动选中第一个
    const actions = filteredActions.value
    if (actions.length && (!selectedActionId.value || !actions.find(a => a.id === selectedActionId.value))) {
      await selectAction(actions[0])
    }
  }

  async function selectAction(action) {
    if (!action) {
      selectedActionId.value = null
      selectedAction.value = null
      selectedProfile.value = null
      return
    }
    selectedActionId.value = action.id
    selectedAction.value = action
    // 加载画像详情
    profileLoading.value = true
    try {
      const res = await getRadarProfile(action.profile_id)
      const detail = res.data?.data
      if (detail) {
        selectedProfile.value = detail.profile
        // 如果画像有更完整的话术，覆盖行动的
        if (detail.active_action) {
          selectedAction.value = { ...selectedAction.value, ...detail.active_action }
        }
      }
    } catch (e) {
      console.error('Failed to load profile:', e)
    } finally {
      profileLoading.value = false
    }
  }

  async function completeAction(id, feedback, note) {
    await completeRadarAction(id, { feedback, note })
    await loadFocus()
    // 选择下一个 pending
    const pending = filteredActions.value.filter(a => a.action_status === 'pending')
    if (pending.length) {
      await selectAction(pending[0])
    } else {
      selectedActionId.value = null
      selectedAction.value = null
      selectedProfile.value = null
    }
  }

  async function dismissAction(id, note) {
    await dismissRadarAction(id, { note })
    await loadFocus()
    const pending = filteredActions.value.filter(a => a.action_status === 'pending')
    if (pending.length) {
      await selectAction(pending[0])
    }
  }

  async function snoozeAction(id, until) {
    await snoozeRadarAction(id, { until })
    await loadFocus()
  }

  async function sendFeedback(actionId, feedback, note) {
    await submitRadarFeedback(actionId, { feedback, note })
    await loadFocus()
  }

  async function loadSources(profileId, type) {
    try {
      const res = await getRadarSourceRecords(profileId, { source_type: type || undefined })
      sourceRecords.value = res.data?.data || []
    } catch (e) {
      console.error('Failed to load sources:', e)
      sourceRecords.value = []
    }
  }

  async function saveNote(profileId, text) {
    await addRadarNote(profileId, { note: text })
  }

  async function refresh() {
    await refreshRadarActions()
    await loadFocus()
    if (selectedActionId.value) {
      const action = allActions.value.find(a => a.id === selectedActionId.value)
      if (action) await selectAction(action)
    }
  }

  onMounted(() => loadFocus())

  return {
    loading, focusData, threadCounts, threadNav,
    selectedThread, selectedActionId, selectedAction, selectedProfile,
    profileLoading, filteredActions, allActions,
    sourceDrawerVisible, sourceRecords, sourceTab, searchKeyword,
    loadFocus, selectThread, selectAction,
    completeAction, dismissAction, snoozeAction, sendFeedback,
    loadSources, saveNote, refresh,
  }
}
