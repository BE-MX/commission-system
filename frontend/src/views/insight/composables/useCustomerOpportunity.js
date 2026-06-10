/**
 * 客户机会台 — 业务逻辑 composable
 *
 * 管理：机会列表、筛选、选中详情、状态更新、反馈、统计。
 * 参考 UI 原型 3 栏布局：左侧筛选 | 中间队列 | 右侧详情
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getMyOpportunities, getOpportunityStats, getOpportunityDetail,
  updateOpportunityStatus, addOpportunityFeedback,
  getAllOpportunities, getUnassignedOpportunities, assignOpportunity,
} from '@/api/insight'
import { useAuthStore } from '@/stores/auth'

export function useCustomerOpportunity() {
  const authStore = useAuthStore()

  // ── 状态 ──────────────────────────────────────────
  const loading = ref(false)
  const opportunities = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const selectedId = ref(null)
  const selectedOpp = ref(null)
  const detailLoading = ref(false)
  const stats = ref({
    total: 0, pending: 0, contacted: 0, replied: 0,
    quoted: 0, won: 0, lost: 0, a_count: 0, overdue: 0, today_contacted: 0,
  })

  // ── 筛选 ──────────────────────────────────────────
  const filters = reactive({
    status: null,
    priority_level: null,
    source: null,
    keyword: '',
  })

  const isAdmin = computed(() => authStore.hasPermission('customer_opportunity:manage'))

  // ── 状态标签 ──────────────────────────────────────
  function statusLabel(s) {
    return {
      pending: '待处理', contacted: '已联系', replied: '有回复',
      quoted: '已报价', won: '已成交', lost: '已流失', dismissed: '已忽略',
    }[s] || s
  }

  // ── 加载列表 ──────────────────────────────────────
  async function reload() {
    loading.value = true
    try {
      const params = {
        page: page.value,
        page_size: pageSize.value,
        ...filters,
      }
      // 清理空值
      Object.keys(params).forEach(k => {
        if (params[k] === null || params[k] === '' || params[k] === undefined) delete params[k]
      })
      const res = isAdmin.value ? await getAllOpportunities(params) : await getMyOpportunities(params)
      const payload = res.data ?? res
      opportunities.value = payload.items || []
      total.value = payload.total || 0
    } catch (e) {
      console.error('Failed to load opportunities:', e)
    } finally {
      loading.value = false
    }
  }

  // ── 加载统计 ──────────────────────────────────────
  async function loadStats() {
    try {
      const res = await getOpportunityStats()
      stats.value = res.data ?? res
    } catch (e) {
      console.error('Failed to load stats:', e)
    }
  }

  // ── 选中机会详情 ──────────────────────────────────
  async function selectOpportunity(id) {
    selectedId.value = id
    if (!id) {
      selectedOpp.value = null
      return
    }
    detailLoading.value = true
    try {
      const res = await getOpportunityDetail(id)
      selectedOpp.value = res.data ?? res
    } catch (e) {
      console.error('Failed to load opportunity detail:', e)
      selectedOpp.value = null
    } finally {
      detailLoading.value = false
    }
  }

  // ── 状态更新 ──────────────────────────────────────
  async function changeStatus(newStatus, note) {
    if (!selectedId.value) return
    try {
      await updateOpportunityStatus(selectedId.value, { status: newStatus, note })
      ElMessage.success(`已标记：${statusLabel(newStatus)}`)
      await reload()
      await selectOpportunity(selectedId.value)
      await loadStats()
    } catch (e) {
      ElMessage.error('状态更新失败')
    }
  }

  // ── 标记已联系并跳转下一条 ──────────────────────
  async function changeStatusAndNext(newStatus, note) {
    if (!selectedId.value) return
    try {
      await updateOpportunityStatus(selectedId.value, { status: newStatus, note })
      await reload()
      await loadStats()
      // 跳转到下一条待处理
      const pending = opportunities.value.filter(o => o.status === 'pending')
      if (pending.length > 0) {
        await selectOpportunity(pending[0].id)
        ElMessage.success('已联系 ✓  已跳转下一条待处理')
      } else {
        selectedOpp.value = null
        selectedId.value = null
        ElMessage.success('已联系 ✓  今日待处理已全部清空')
      }
    } catch (e) {
      ElMessage.error('状态更新失败')
    }
  }

  // ── 反馈 ──────────────────────────────────────────
  async function submitFeedback(feedback, note) {
    if (!selectedId.value) return
    try {
      await addOpportunityFeedback(selectedId.value, { feedback, note })
      ElMessage.success('反馈已记录')
      await selectOpportunity(selectedId.value)
    } catch (e) {
      ElMessage.error('反馈提交失败')
    }
  }

  // ── 管理员: 分配 ──────────────────────────────────
  async function assignToUser(oppId, userId) {
    try {
      await assignOpportunity(oppId, userId)
      ElMessage.success('已分配')
      await reload()
      await loadStats()
    } catch (e) {
      ElMessage.error('分配失败')
    }
  }

  // ── 分页 ──────────────────────────────────────────
  function handlePageChange(val) {
    page.value = val
    reload()
  }

  // ── 筛选变更 ──────────────────────────────────────
  function applyFilters() {
    page.value = 1
    reload()
  }

  // ── 初始化 ────────────────────────────────────────
  onMounted(() => {
    reload()
    loadStats()
  })

  return {
    loading, opportunities, total, page, pageSize,
    selectedId, selectedOpp, detailLoading, stats, filters,
    isAdmin,
    reload, loadStats, selectOpportunity, changeStatus, changeStatusAndNext,
    submitFeedback, assignToUser, handlePageChange, applyFilters,
  }
}
