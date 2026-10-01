import { TASK_STATUS_LABELS as TASK_STATUS_MAP, TASK_STATUS_TYPES as TASK_STATUS_TAG } from '../designStatus.js'
import { msgWarning, msgSuccessText, confirmAction } from '@/utils/feedback'
/**
 * 设计管理页 — 业务逻辑 composable
 *
 * 集中四个 tab (Pending/Scheduled/Completed/Designers) + 5+ Dialog 的 state + 方法:
 *   - 字典加载 (shoot_type / customer_level)
 *   - 各 tab fetch + 筛选
 *   - Edit dialogs: expect-date / remark / shoot-type / task-date / designer-inline
 *   - Confirm dialog (排期确认 + 选择设计师)
 *   - Task actions (start/complete/cancel)
 *   - Designer CRUD + 启用切换
 *   - Gantt reschedule callback
 *   - Excel import
 *
 * 主文件保留 template + style + composable destructure + 子组件 import。
 */
import { computed, ref, reactive, onMounted, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { designActorScope, watchDesignActor } from '../designListScope'

import {
  getRequests, getTaskList, getDesigners, createDesigner, updateDesigner,
  actionRequest, rescheduleTask, importRequests,
  updateExpectDate, updateRequestRemark, updateTaskRemark, updateRequestShootType, updateTaskShootType,
  triggerShootReminderScan,
} from '@/api/design'
import { getDictMap } from '@/utils/dict'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'

const PERIOD_LABELS = { am: '上午', pm: '下午' }



// 列配置数组：TableTools 列显隐的数据源（Action Bar Spec；操作列不进配置，列保持模板静态渲染）
const PENDING_COLUMNS = [
  { key: 'request-no', label: '预约编号' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'customer-level', label: '客户等级' },
  { key: 'salesperson', label: '业务员' },
  { key: 'shoot-type', label: '拍摄类型' },
  { key: 'expect-date', label: '期望日期' },
  { key: 'priority', label: '优先级' },
  { key: 'remark', label: '备注' },
  { key: 'created-at', label: '创建时间' },
]
const SCHEDULED_COLUMNS = [
  { key: 'task-no', label: '任务编号' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'salesperson', label: '业务员' },
  { key: 'shoot-type', label: '拍摄类型' },
  { key: 'designer', label: '设计师' },
  { key: 'plan-date', label: '排期日期' },
  { key: 'priority', label: '优先级' },
  { key: 'remark', label: '备注' },
  { key: 'status', label: '状态' },
  { key: 'created-at', label: '创建时间' },
]
const COMPLETED_COLUMNS = [
  { key: 'task-no', label: '任务编号' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'salesperson', label: '业务员' },
  { key: 'shoot-type', label: '拍摄类型' },
  { key: 'designer', label: '设计师' },
  { key: 'plan-date', label: '排期日期' },
  { key: 'priority', label: '优先级' },
  { key: 'status', label: '状态' },
  { key: 'created-at', label: '创建时间' },
]
const DESIGNER_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '姓名' },
  { key: 'email', label: '邮箱' },
  { key: 'dingtalk-id', label: '钉钉ID' },
  { key: 'status', label: '状态' },
  { key: 'created-at', label: '创建时间' },
]

function periodLabel(p) { return PERIOD_LABELS[p] || '' }

// 每 tab 一套表格视图状态（列显隐/密度/全屏），localStorage 键各自独立（Action Bar Spec）
function useTabTableView(tab, columns) {
  const {
    density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen,
  } = useTableView(`design-manage-${tab}`, columns)
  return { columnDefs: columns, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen }
}

export function useDesignManage() {
  const authStore = useAuthStore()
  const readScope = () => designActorScope(authStore)
  // ── 排序 ──────────────────────────────────────────────
  const pendingSort = useTableSort()
  const scheduledSort = useTableSort()
  const completedSort = useTableSort()

  // ── 表格视图（每 tab 独立） ────────────────────────────
  const pendingView = useTabTableView('pending', PENDING_COLUMNS)
  const scheduledView = useTabTableView('scheduled', SCHEDULED_COLUMNS)
  const completedView = useTabTableView('completed', COMPLETED_COLUMNS)
  const designerView = useTabTableView('designers', DESIGNER_COLUMNS)

  // ── 字典 ──────────────────────────────────────────────
  const shootTypeMap = ref({})
  const customerLevelMap = ref({})
  async function loadShootTypeDict() {
    shootTypeMap.value = await getDictMap('shoot_type')
    customerLevelMap.value = await getDictMap('customer_level')
  }
  function customerLevelLabel(code) {
    if (!code) return '-'
    return customerLevelMap.value[code] || code
  }
  function getDesignerName(id) {
    const d = designerData.value.find(d => d.id === id)
    return d ? d.name : id || '-'
  }

  // ── Tab / Detail drawer ───────────────────────────────
  const activeTab = ref('pending')
  const tabMaxHeight = ref(700)
  const calendarConfigRef = ref() // 不可用日期 tab 的 DesignCalendarConfig 实例
  const detailVisible = ref(false)
  const detailRequestId = ref(null)
  watch(readScope, () => { detailVisible.value = false; detailRequestId.value = null }, { flush: 'sync' })

  function openDetail(requestId) {
    detailRequestId.value = requestId
    detailVisible.value = true
  }

  // ── Edit expect date (pending) ────────────────────────
  const editDateVisible = ref(false)
  const editDateSaving = ref(false)
  const editDateRow = ref(null)
  const editDateForm = reactive({ startDate: '', startPeriod: 'am', endDate: '', endPeriod: 'pm' })

  function openEditDateDialog(row) {
    editDateRow.value = row
    editDateForm.startDate = row.expect_start_date || ''
    editDateForm.startPeriod = row.expect_start_period || 'am'
    editDateForm.endDate = row.expect_end_date || ''
    editDateForm.endPeriod = row.expect_end_period || 'pm'
    editDateVisible.value = true
  }

  async function submitEditDate() {
    if (!editDateForm.startDate || !editDateForm.endDate) {
      msgWarning('请选择日期')
      return
    }
    editDateSaving.value = true
    try {
      await updateExpectDate(editDateRow.value.id, {
        expect_start_date: editDateForm.startDate,
        expect_start_period: editDateForm.startPeriod,
        expect_end_date: editDateForm.endDate,
        expect_end_period: editDateForm.endPeriod,
      })
      msgSuccessText('期望日期已更新')
      editDateVisible.value = false
      pendingState.refreshUpdate()
    } finally {
      editDateSaving.value = false
    }
  }

  // ── Edit request / task remark ─────────────────────────────
  const remarkVisible = ref(false)
  const remarkSaving = ref(false)
  const remarkRow = ref(null)
  const remarkTarget = ref('request')
  const remarkForm = reactive({ remark: '' })

  function openRemarkDialog(row, target = 'request') {
    remarkRow.value = row
    remarkTarget.value = target
    remarkForm.remark = (target === 'request' && row.request_id ? row.request_remark : row.remark) || ''
    remarkVisible.value = true
  }

  async function submitRemark() {
    if (remarkSaving.value) return
    remarkSaving.value = true
    try {
      const row = remarkRow.value
      const remark = remarkForm.remark
      if (remarkTarget.value === 'task') {
        await updateTaskRemark(row.id, { remark })
        row.remark = remark
      } else {
        await updateRequestRemark(row.request_id || row.id, { remark })
        if (row.request_id) row.request_remark = remark
        else row.remark = remark
      }
      msgSuccessText('备注已更新')
      remarkVisible.value = false
      if (activeTab.value === 'scheduled') scheduledState.refreshUpdate()
      else pendingState.refreshUpdate()
    } catch {
      // API interceptor displays the error; keep the draft open for retry.
    } finally {
      remarkSaving.value = false
    }
  }

  // ── Edit shoot type (both tabs) ───────────────────────
  const shootTypeVisible = ref(false)
  const shootTypeSaving = ref(false)
  const shootTypeRow = ref(null)
  const shootTypeTarget = ref('request')
  const shootTypeForm = reactive({ shoot_type: [] })

  function openShootTypeDialog(row, target) {
    shootTypeRow.value = row
    shootTypeTarget.value = target
    shootTypeForm.shoot_type = row.shoot_type ? row.shoot_type.split(',').filter(Boolean) : []
    shootTypeVisible.value = true
  }

  async function submitShootType() {
    if (!shootTypeForm.shoot_type || shootTypeForm.shoot_type.length === 0) {
      msgWarning('请选择拍摄类型')
      return
    }
    shootTypeSaving.value = true
    try {
      const shootTypeStr = shootTypeForm.shoot_type.join(',')
      if (shootTypeTarget.value === 'request') {
        await updateRequestShootType(shootTypeRow.value.id, {
          shoot_type: shootTypeStr,
          operator_id: 1,
          operator_name: '管理员',
        })
        pendingState.refreshUpdate()
      } else {
        await updateTaskShootType(shootTypeRow.value.id, {
          shoot_type: shootTypeStr,
          operator_id: 1,
          operator_name: '管理员',
        })
        scheduledState.refreshUpdate()
      }
      msgSuccessText('拍摄类型已更新')
      shootTypeVisible.value = false
    } finally {
      shootTypeSaving.value = false
    }
  }

  // ── Designer inline edit (scheduled tab) ──────────────
  const editingDesignerId = ref(null)
  const editingDesignerValue = ref(null)

  function startEditDesigner(row) {
    editingDesignerId.value = row.id
    editingDesignerValue.value = row.designer_id
  }

  function cancelEditDesigner() {
    editingDesignerId.value = null
    editingDesignerValue.value = null
  }

  async function saveDesigner(row) {
    if (editingDesignerValue.value === row.designer_id) {
      editingDesignerId.value = null
      return
    }
    try {
      await rescheduleTask(row.id, {
        designer_id: editingDesignerValue.value,
        plan_start_date: row.plan_start_date,
        plan_start_period: row.plan_start_period || 'am',
        plan_end_date: row.plan_end_date,
        plan_end_period: row.plan_end_period || 'pm',
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      msgSuccessText('设计师已更新')
      scheduledState.refreshUpdate()
    } catch { /* handled by interceptor */ }
    editingDesignerId.value = null
  }

  // ── Edit task date (scheduled tab) ────────────────────
  const editTaskDateVisible = ref(false)
  const editTaskDateSaving = ref(false)
  const editTaskDateRow = ref(null)
  const editTaskDateForm = reactive({
    startDate: '', startPeriod: 'am', endDate: '', endPeriod: 'pm', comment: '',
  })

  function openEditTaskDateDialog(row) {
    editTaskDateRow.value = row
    editTaskDateForm.startDate = row.plan_start_date || ''
    editTaskDateForm.startPeriod = row.plan_start_period || 'am'
    editTaskDateForm.endDate = row.plan_end_date || ''
    editTaskDateForm.endPeriod = row.plan_end_period || 'pm'
    editTaskDateForm.comment = ''
    editTaskDateVisible.value = true
  }

  async function submitEditTaskDate() {
    if (!editTaskDateForm.startDate || !editTaskDateForm.endDate) {
      msgWarning('请选择日期')
      return
    }
    editTaskDateSaving.value = true
    try {
      await rescheduleTask(editTaskDateRow.value.id, {
        plan_start_date: editTaskDateForm.startDate,
        plan_start_period: editTaskDateForm.startPeriod,
        plan_end_date: editTaskDateForm.endDate,
        plan_end_period: editTaskDateForm.endPeriod,
        comment: editTaskDateForm.comment,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      msgSuccessText('排期日期已更新')
      editTaskDateVisible.value = false
      scheduledState.refreshUpdate()
    } finally {
      editTaskDateSaving.value = false
    }
  }

  // ── Pending tab ───────────────────────────────────────
  const pendingTableRef = ref()
  const pendingState = useListPage(async (params, { signal }) => {
    const { expectDateRange, ...query } = params
    if (expectDateRange?.length === 2) { query.expect_start_date = expectDateRange[0]; query.expect_end_date = expectDateRange[1] }
    query.status = 'pending_design'
    query.operator_id = 1; query.operator_role = 'design_staff'
    if (!query.salesperson_name) delete query.salesperson_name
    if (!query.shoot_type) delete query.shoot_type
    if (!query.designer_id) delete query.designer_id
    const response = await getRequests(query, { signal, suppressToast: true })
    const data = response.data
    return { items: data?.items || data || [], total: data?.total || 0 }
  }, { immediate: false, pageSize: 20, searchForm: { salesperson_name: '', shoot_type: '', expectDateRange: null }, sortParams: pendingSort.sortParams.value })
  watchDesignActor(pendingState, readScope)
  const pendingData = pendingState.list; const pendingLoading = pendingState.loading
  const pendingPage = pendingState.page; const pendingPageSize = pendingState.pageSize; const pendingTotal = pendingState.total
  const pendingFilters = pendingState.searchForm
  const pendingHasActiveFilters = computed(() => Boolean(pendingFilters.salesperson_name || pendingFilters.shoot_type || pendingFilters.expectDateRange?.length))
  const searchPending = pendingState.handleSearch
  const resetPendingFilters = pendingState.handleReset
  const handlePendingSizeChange = pendingState.handleSizeChange
  const fetchPending = pendingState.fetchList
  function handlePendingSortChange(info) { pendingSort.onSortChange(info); return pendingState.handleSortChange(pendingSort.sortParams.value) }

  async function handleScanShootReminders() {
    try {
      await confirmAction(
        '将立即扫描今日待确认和已排期任务并向相关人员推送钉钉拍摄提醒，是否继续？',
        '预约任务扫描',
        { type: 'info', confirmButtonText: '开始扫描', cancelButtonText: '取消' },
      )
    } catch { return }
    try {
      await triggerShootReminderScan()
      msgSuccessText('扫描已完成，相关提醒已推送')
    } catch { /* handled by interceptor */ }
  }

  // ── Scheduled tab ─────────────────────────────────────
  const scheduledTableRef = ref()
  const scheduledState = useListPage(async (params, { signal }) => {
    const { planDateRange, ...query } = params
    if (planDateRange?.length === 2) { query.plan_start_date = planDateRange[0]; query.plan_end_date = planDateRange[1] }
    query.status = 'scheduled,in_progress'
    query.operator_id = 1; query.operator_role = 'design_staff'
    if (!query.salesperson_name) delete query.salesperson_name
    if (!query.shoot_type) delete query.shoot_type
    if (!query.designer_id) delete query.designer_id
    const response = await getTaskList(query, { signal, suppressToast: true })
    const data = response.data
    return { items: data?.items || data || [], total: data?.total || 0 }
  }, { immediate: false, pageSize: 20, searchForm: { salesperson_name: '', shoot_type: '', designer_id: null, planDateRange: null }, sortParams: scheduledSort.sortParams.value })
  watchDesignActor(scheduledState, readScope)
  const scheduledData = scheduledState.list; const scheduledLoading = scheduledState.loading
  const scheduledPage = scheduledState.page; const scheduledPageSize = scheduledState.pageSize; const scheduledTotal = scheduledState.total
  const scheduledFilters = scheduledState.searchForm
  const scheduledHasActiveFilters = computed(() => Boolean(scheduledFilters.salesperson_name || scheduledFilters.shoot_type || scheduledFilters.designer_id || scheduledFilters.planDateRange?.length))
  const searchScheduled = scheduledState.handleSearch
  const resetScheduledFilters = scheduledState.handleReset
  const handleScheduledSizeChange = scheduledState.handleSizeChange
  const fetchScheduled = scheduledState.fetchList
  function handleScheduledSortChange(info) { scheduledSort.onSortChange(info); return scheduledState.handleSortChange(scheduledSort.sortParams.value) }

  // ── Completed tab ─────────────────────────────────────
  const completedTableRef = ref()
  const completedState = useListPage(async (params, { signal }) => {
    const { planDateRange, ...query } = params
    if (planDateRange?.length === 2) { query.plan_start_date = planDateRange[0]; query.plan_end_date = planDateRange[1] }
    query.status = 'completed'
    query.operator_id = 1; query.operator_role = 'design_staff'
    if (!query.salesperson_name) delete query.salesperson_name
    if (!query.shoot_type) delete query.shoot_type
    if (!query.designer_id) delete query.designer_id
    const response = await getTaskList(query, { signal, suppressToast: true })
    const data = response.data
    return { items: data?.items || data || [], total: data?.total || 0 }
  }, { immediate: false, pageSize: 20, searchForm: { salesperson_name: '', shoot_type: '', designer_id: null, planDateRange: null }, sortParams: completedSort.sortParams.value })
  watchDesignActor(completedState, readScope)
  const completedData = completedState.list; const completedLoading = completedState.loading
  const completedPage = completedState.page; const completedPageSize = completedState.pageSize; const completedTotal = completedState.total
  const completedFilters = completedState.searchForm
  const completedHasActiveFilters = computed(() => Boolean(completedFilters.salesperson_name || completedFilters.shoot_type || completedFilters.designer_id || completedFilters.planDateRange?.length))
  const searchCompleted = completedState.handleSearch
  const resetCompletedFilters = completedState.handleReset
  const handleCompletedSizeChange = completedState.handleSizeChange
  const fetchCompleted = completedState.fetchList
  function handleCompletedSortChange(info) { completedSort.onSortChange(info); return completedState.handleSortChange(completedSort.sortParams.value) }

  // ── Designers tab ─────────────────────────────────────
  const designerResource = useAsyncResource(async (_, { signal }) => (await getDesigners({ signal, suppressToast: true })).data || [])
  const designerData = computed(() => designerResource.data.value || [])
  const designerLoading = designerResource.loading
  const fetchDesigners = () => designerResource.load()
  watch(readScope, () => designerResource.load(null, { clear: true }), { flush: 'sync' })

  // ── Tab change ────────────────────────────────────────
  function onTabChange(tab) {
    if (tab === 'pending') fetchPending()
    else if (tab === 'scheduled') fetchScheduled()
    else if (tab === 'completed') fetchCompleted()
    else if (tab === 'designers') fetchDesigners()
    // 排期改期会联动增删不可用日期，切回日历 tab 必须重拉
    // （lazy tab 首次激活时组件尚未挂载，ref 为空 → 由其 onMounted 自行加载）
    else if (tab === 'unavailable') calendarConfigRef.value?.fetchDates()
  }

  // ── Designer create/edit ──────────────────────────────
  const designerDialogVisible = ref(false)
  const designerSaving = ref(false)
  const designerForm = reactive({
    id: null, name: '', email: '', dingtalk_id: '', is_active: true,
  })

  function openDesignerDialog(row) {
    if (row) {
      designerForm.id = row.id
      designerForm.name = row.name
      designerForm.email = row.email || ''
      designerForm.dingtalk_id = row.dingtalk_id || ''
      designerForm.is_active = row.is_active
    } else {
      designerForm.id = null
      designerForm.name = ''
      designerForm.email = ''
      designerForm.dingtalk_id = ''
      designerForm.is_active = true
    }
    designerDialogVisible.value = true
  }

  async function submitDesigner() {
    if (!designerForm.name.trim()) {
      msgWarning('请输入设计师姓名')
      return
    }
    designerSaving.value = true
    try {
      const payload = {
        name: designerForm.name.trim(),
        email: designerForm.email || null,
        dingtalk_id: designerForm.dingtalk_id || null,
        is_active: designerForm.is_active,
      }
      if (designerForm.id) {
        await updateDesigner(designerForm.id, payload)
      } else {
        await createDesigner(payload)
      }
      msgSuccessText('保存成功')
      designerDialogVisible.value = false
      fetchDesigners()
    } finally {
      designerSaving.value = false
    }
  }

  async function toggleDesignerActive(row) {
    const action = row.is_active ? '停用' : '启用'
    try {
      await confirmAction(`确定${action}设计师「${row.name}」？`, '确认', { type: 'warning' })
    } catch { return }

    try {
      await updateDesigner(row.id, { is_active: !row.is_active })
      msgSuccessText(`${action}成功`)
      fetchDesigners()
    } catch { /* handled */ }
  }

  // ── Confirm scheduling dialog ─────────────────────────
  const confirmVisible = ref(false)
  const confirmRow = ref(null)
  const confirming = ref(false)
  const confirmForm = reactive({
    designer_id: null,
    startDate: '', startPeriod: 'am',
    endDate: '', endPeriod: 'pm',
    comment: '',
    sync_unavailable: true,
  })

  function openConfirmDialog(row) {
    confirmRow.value = row
    confirmForm.designer_id = row.preferred_designer_id || null
    confirmForm.startDate = row.expect_start_date || ''
    confirmForm.startPeriod = row.expect_start_period || 'am'
    confirmForm.endDate = row.expect_end_date || ''
    confirmForm.endPeriod = row.expect_end_period || 'pm'
    confirmForm.comment = ''
    confirmVisible.value = true
    if (!designerData.value.length) fetchDesigners()
  }

  async function submitConfirm() {
    if (!confirmForm.designer_id) {
      msgWarning('请选择设计师')
      return
    }
    if (!confirmForm.startDate || !confirmForm.endDate) {
      msgWarning('请选择排期日期')
      return
    }
    confirming.value = true
    try {
      await actionRequest(confirmRow.value.id, {
        action: 'confirm',
        designer_id: confirmForm.designer_id,
        plan_start_date: confirmForm.startDate,
        plan_start_period: confirmForm.startPeriod,
        plan_end_date: confirmForm.endDate,
        plan_end_period: confirmForm.endPeriod,
        comment: confirmForm.comment,
        sync_unavailable: confirmForm.sync_unavailable,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      msgSuccessText('排期确认成功')
      confirmVisible.value = false
      pendingState.refreshRemove(); scheduledState.refreshCreate()
    } finally {
      confirming.value = false
    }
  }

  // ── Task actions ──────────────────────────────────────
  async function handleTaskAction(row, action) {
    const labels = { start: '开始执行', complete: '标记完成', cancel: '取消任务' }
    try {
      await confirmAction(`确定${labels[action]}？`, '确认', {
        type: action === 'cancel' ? 'warning' : 'info',
      })
    } catch { return }

    try {
      await actionRequest(row.request_id || row.id, {
        action,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      msgSuccessText('操作成功')
      if (action === 'complete' || action === 'cancel') scheduledState.refreshRemove()
      else scheduledState.refreshUpdate()
      if (action === 'complete') completedState.refreshCreate()
    } catch { /* handled by interceptor */ }
  }

  // ── Gantt reschedule callback ─────────────────────────
  async function handleReschedule({ taskId, planStartDate, planStartPeriod, planEndDate, planEndPeriod, task }) {
    const pLabels = { am: '上午', pm: '下午' }
    try {
      await confirmAction(
        `确定将任务 "${task.task_name || task.task_no}" 的排期调整为 ${planStartDate} ${pLabels[planStartPeriod] || ''} ~ ${planEndDate} ${pLabels[planEndPeriod] || ''}？`,
        '调整排期',
        { type: 'warning' },
      )
    } catch { return }

    try {
      await rescheduleTask(taskId, {
        plan_start_date: planStartDate,
        plan_start_period: planStartPeriod || 'am',
        plan_end_date: planEndDate,
        plan_end_period: planEndPeriod || 'pm',
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      msgSuccessText('排期已调整')
      scheduledState.refreshUpdate()
    } catch { /* handled by interceptor */ }
  }

  // ── Layout util ───────────────────────────────────────
  function updateTabMaxHeight() {
    tabMaxHeight.value = Math.max(400, window.innerHeight - 200)
  }

  // ── Excel import ──────────────────────────────────────
  const uploadRef = ref()
  const importFile = ref(null)
  const importing = ref(false)
  const importResultVisible = ref(false)
  const importResult = ref(null)

  function onFileChange(file) {
    importFile.value = file.raw
  }

  async function submitImport() {
    if (!importFile.value) return
    importing.value = true
    try {
      const formData = new FormData()
      formData.append('file', importFile.value)
      const res = await importRequests(formData, {
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'salesperson',
      })
      importResult.value = res.data
      importResultVisible.value = true
      importFile.value = null
      if (uploadRef.value) uploadRef.value.clearFiles()
      pendingState.refreshCreate()
    } catch {
      // handled by interceptor
    } finally {
      importing.value = false
    }
  }

  // ── Lifecycle ─────────────────────────────────────────
  onMounted(() => {
    updateTabMaxHeight()
    window.addEventListener('resize', updateTabMaxHeight)
    loadShootTypeDict()
    fetchPending()
    fetchDesigners()
  })

  return {
    // 字典 / 工具
    shootTypeMap, customerLevelMap, customerLevelLabel, getDesignerName,
    periodLabel, TASK_STATUS_MAP, TASK_STATUS_TAG,
    // Tab + Detail
    activeTab, tabMaxHeight, detailVisible, detailRequestId, openDetail, onTabChange,
    calendarConfigRef,
    // Edit dialogs
    editDateVisible, editDateSaving, editDateForm, openEditDateDialog, submitEditDate,
    remarkVisible, remarkSaving, remarkTarget, remarkForm, openRemarkDialog, submitRemark,
    shootTypeVisible, shootTypeSaving, shootTypeTarget, shootTypeForm,
    openShootTypeDialog, submitShootType,
    editingDesignerId, editingDesignerValue,
    startEditDesigner, cancelEditDesigner, saveDesigner,
    editTaskDateVisible, editTaskDateSaving, editTaskDateForm,
    openEditTaskDateDialog, submitEditTaskDate,
    // Pending tab
    pendingTableRef, pendingData, pendingLoading,
    pendingPage, pendingPageSize, pendingTotal, pendingFilters,
    pendingState, fetchPending, handleScanShootReminders, pendingSort, handlePendingSortChange,
    pendingHasActiveFilters, searchPending, resetPendingFilters, handlePendingSizeChange,
    pendingColumnDefs: pendingView.columnDefs,
    pendingDensity: pendingView.density,
    pendingDensityClass: pendingView.densityClass,
    pendingVisibleKeys: pendingView.visibleKeys,
    pendingPanelRef: pendingView.panelRef,
    pendingIsFullscreen: pendingView.isFullscreen,
    pendingToggleFullscreen: pendingView.toggleFullscreen,
    // Scheduled tab
    scheduledTableRef, scheduledData, scheduledLoading,
    scheduledPage, scheduledPageSize, scheduledTotal, scheduledFilters,
    scheduledState, fetchScheduled, scheduledSort, handleScheduledSortChange,
    scheduledHasActiveFilters, searchScheduled, resetScheduledFilters, handleScheduledSizeChange,
    scheduledColumnDefs: scheduledView.columnDefs,
    scheduledDensity: scheduledView.density,
    scheduledDensityClass: scheduledView.densityClass,
    scheduledVisibleKeys: scheduledView.visibleKeys,
    scheduledPanelRef: scheduledView.panelRef,
    scheduledIsFullscreen: scheduledView.isFullscreen,
    scheduledToggleFullscreen: scheduledView.toggleFullscreen,
    // Completed tab
    completedTableRef, completedData, completedLoading,
    completedPage, completedPageSize, completedTotal, completedFilters,
    completedState, fetchCompleted, completedSort, handleCompletedSortChange,
    completedHasActiveFilters, searchCompleted, resetCompletedFilters, handleCompletedSizeChange,
    completedColumnDefs: completedView.columnDefs,
    completedDensity: completedView.density,
    completedDensityClass: completedView.densityClass,
    completedVisibleKeys: completedView.visibleKeys,
    completedPanelRef: completedView.panelRef,
    completedIsFullscreen: completedView.isFullscreen,
    completedToggleFullscreen: completedView.toggleFullscreen,
    // Designers tab
    designerResource, designerData, designerLoading, fetchDesigners,
    designerColumnDefs: designerView.columnDefs,
    designerDensity: designerView.density,
    designerDensityClass: designerView.densityClass,
    designerVisibleKeys: designerView.visibleKeys,
    designerPanelRef: designerView.panelRef,
    designerIsFullscreen: designerView.isFullscreen,
    designerToggleFullscreen: designerView.toggleFullscreen,
    designerDialogVisible, designerSaving, designerForm,
    openDesignerDialog, submitDesigner, toggleDesignerActive,
    // Confirm dialog
    confirmVisible, confirmRow, confirming, confirmForm,
    openConfirmDialog, submitConfirm,
    // Task action / Gantt
    handleTaskAction, handleReschedule,
    // Import
    uploadRef, importFile, importing,
    importResultVisible, importResult,
    onFileChange, submitImport,
  }
}
