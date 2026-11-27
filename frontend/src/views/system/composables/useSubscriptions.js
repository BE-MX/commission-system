/**
 * AI 订阅管理 composable：汇总条、多维筛选排序、卡片/表格视图、续费确认、余额流水与 LOGO 缓存。
 */
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import {
  confirmProviderRenew,
  createBalanceCheckpoint,
  getProviderLogoBlob,
  getSubscriptions,
} from '@/api/ai'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { confirmAction, msgSuccessText } from '@/utils/feedback'

const MERGE_NOTICE_KEY = 'ark_ai_merge_notice_dismissed_v1'

const EMPTY_SUMMARY = {
  month_spend: [],
  total_spend: [],
  fixed_subscriptions_monthly: [],
  unpriced_count: 0,
  no_usage_count: 0,
  test_count: 0,
  total_providers: 0,
  active_count: 0,
  renew_alert_count: 0,
  balance_alert_count: 0,
  disabled_count: 0,
}

export function useSubscriptions({ onMutated, onBalanceRecorded } = {}) {
  const filters = reactive({
    statusFilter: 'all',
    serviceKind: '',
    apiType: '',
    hideDisabled: false,
    search: '',
    sort: 'renew',
  })

  const viewMode = ref('card')
  const showMergeNotice = ref(
    typeof window !== 'undefined' ? window.localStorage.getItem(MERGE_NOTICE_KEY) !== '1' : true,
  )

  const logoUrls = ref({})
  let unmounted = false

  const resource = useAsyncResource(
    async (_, { signal }) => {
      const res = await getSubscriptions({}, { signal, suppressToast: true })
      return res.data || { summary: EMPTY_SUMMARY, total: 0, items: [] }
    },
    { initialData: { summary: EMPTY_SUMMARY, total: 0, items: [] } },
  )

  const summary = computed(() => resource.data.value?.summary || EMPTY_SUMMARY)
  const rawItems = computed(() => resource.data.value?.items || [])

  async function refreshLogo(providerId, hasLogo, { bust = false } = {}) {
    if (!hasLogo) {
      if (logoUrls.value[providerId]) {
        URL.revokeObjectURL(logoUrls.value[providerId])
        const next = { ...logoUrls.value }
        delete next[providerId]
        logoUrls.value = next
      }
      return
    }
    try {
      const config = bust ? { params: { v: Date.now() } } : {}
      const res = await getProviderLogoBlob(providerId, config)
      if (unmounted) return
      const blob = res?.data instanceof Blob ? res.data : (res instanceof Blob ? res : null)
      if (!blob) return
      const url = URL.createObjectURL(blob)
      if (unmounted) {
        URL.revokeObjectURL(url)
        return
      }
      if (logoUrls.value[providerId]) URL.revokeObjectURL(logoUrls.value[providerId])
      logoUrls.value = { ...logoUrls.value, [providerId]: url }
    } catch {
      /* 无 LOGO 或读取失败时回退到首字字标 */
    }
  }

  async function fetchSubscriptions() {
    const data = await resource.load()
    const items = data?.items || []
    const activeLogoIds = new Set(items.filter(item => item.billing?.has_logo).map(item => String(item.id)))
    for (const existingId of Object.keys(logoUrls.value)) {
      if (!activeLogoIds.has(existingId)) {
        URL.revokeObjectURL(logoUrls.value[existingId])
        const next = { ...logoUrls.value }
        delete next[existingId]
        logoUrls.value = next
      }
    }
    await Promise.all(items.filter(item => item.billing?.has_logo).map(item => refreshLogo(item.id, true)))
    return data
  }

  const filteredItems = computed(() => {
    const needle = filters.search.trim().toLowerCase()
    let list = rawItems.value.filter(item => {
      if (filters.statusFilter === 'renew_alert' && !['renew_pending', 'renew_soon'].includes(item.renew_flag)) return false
      if (filters.statusFilter === 'balance_alert' && !['balance_empty', 'balance_low'].includes(item.balance_flag)) return false
      if (filters.statusFilter === 'disabled' && item.is_enabled) return false
      if (filters.hideDisabled && !item.is_enabled) return false
      if (filters.serviceKind && item.service_kind !== filters.serviceKind) return false
      if (filters.apiType && (item.provider_type !== 'direct' || item.api_type !== filters.apiType)) return false
      if (needle) {
        const hitName = item.name.toLowerCase().includes(needle)
        const hitBase = (item.api_base || '').toLowerCase().includes(needle)
        const hitModel = (item.models || []).some(m => m.toLowerCase().includes(needle))
        if (!hitName && !hitBase && !hitModel) return false
      }
      return true
    })

    const monthAmount = (item, cur) => {
      const found = (item.spend?.month || []).find(entry => entry.currency === cur)
      return found ? Number(found.amount) : 0
    }

    list = [...list]
    if (filters.sort === 'balance') {
      list.sort((a, b) => {
        const ra = a.balance?.remaining_pct ?? 9999
        const rb = b.balance?.remaining_pct ?? 9999
        return ra - rb || a.id - b.id
      })
    } else if (filters.sort === 'month') {
      list.sort((a, b) => {
        const ac = monthAmount(a, 'CNY')
        const bc = monthAmount(b, 'CNY')
        const au = monthAmount(a, 'USD')
        const bu = monthAmount(b, 'USD')
        const ga = ac > 0 ? 0 : (au > 0 ? 1 : 2)
        const gb = bc > 0 ? 0 : (bu > 0 ? 1 : 2)
        return ga - gb || bc - ac || bu - au || a.id - b.id
      })
    } else {
      list.sort((a, b) => {
        const da = a.renew?.days_left ?? 1e9
        const db = b.renew?.days_left ?? 1e9
        return da - db || a.id - b.id
      })
    }
    return list
  })

  function toggleStatusCard(target) {
    filters.statusFilter = filters.statusFilter === target ? 'all' : target
  }

  function dismissMergeNotice() {
    showMergeNotice.value = false
    if (typeof window !== 'undefined') window.localStorage.setItem(MERGE_NOTICE_KEY, '1')
  }

  const balanceModalVisible = ref(false)
  const balanceTarget = ref(null)
  const balanceSaving = ref(false)

  function openBalanceModal(item) {
    const latest = rawItems.value.find(row => row.id === item?.id) || item
    balanceTarget.value = latest
    balanceModalVisible.value = true
  }

  async function submitBalanceCheckpoint(payload) {
    if (!balanceTarget.value) return
    const targetId = balanceTarget.value.id
    balanceSaving.value = true
    try {
      await createBalanceCheckpoint(targetId, payload)
      msgSuccessText('余额流水已登记')
      balanceModalVisible.value = false
      await fetchSubscriptions()
      if (onBalanceRecorded) await onBalanceRecorded(targetId)
      if (onMutated) await onMutated()
    } finally {
      balanceSaving.value = false
    }
  }

  async function handleConfirmRenew(item) {
    try {
      await confirmAction(
        `确认「${item.name}」已完成续费？系统将把下次续费日期顺延一个计费周期。`,
        '确认续费',
        { type: 'info' },
      )
      await confirmProviderRenew(item.id)
      msgSuccessText('已确认续费并顺延一期')
      await fetchSubscriptions()
      if (onMutated) await onMutated()
    } catch (err) {
      if (err !== 'cancel') { /* shared client handles toast */ }
    }
  }

  onBeforeUnmount(() => {
    unmounted = true
    Object.values(logoUrls.value).forEach(url => URL.revokeObjectURL(url))
  })

  return {
    resource,
    loading: resource.loading,
    summary,
    rawItems,
    filteredItems,
    filters,
    viewMode,
    showMergeNotice,
    logoUrls,
    balanceModalVisible,
    balanceTarget,
    balanceSaving,
    fetchSubscriptions,
    refreshLogo,
    toggleStatusCard,
    dismissMergeNotice,
    openBalanceModal,
    submitBalanceCheckpoint,
    handleConfirmRenew,
  }
}
